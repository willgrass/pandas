"""A collection of random tools for dealing with dates in Python"""

from datetime import datetime, timedelta
from dateutil import parser
from dateutil.relativedelta import relativedelta
import calendar

#-------------------------------------------------------------------------------
# Miscellaneous date functions

def format(dt):
    """Returns date in YYYYMMDD format."""
    return dt.strftime('%Y%m%d')

OLE_TIME_ZERO = datetime(1899, 12, 30, 0, 0, 0)

def ole2datetime(oledt):
    """function for converting excel date to normal date format"""
    # Excel has a bug where it thinks the date 2/29/1900 exists
    # we just reject any date before 3/1/1900.
    val = float(oledt)
    if val < 61:
        raise Exception("Value is outside of acceptable range: %s " % val)
    return OLE_TIME_ZERO + timedelta(days=val)

def to_datetime(input):
    """Attempts to convert input to datetime"""
    if input is None or isinstance(input, datetime):
        return input
    try:
        return parser.parse(input)
    except Exception:
        return input

def normalize_date(dt):
    return datetime(dt.year, dt.month, dt.day)

#-------------------------------------------------------------------------------
# DateOffset

class DateOffset(object):
    """
    Standard kind of date increment used for a date range.

    Works exactly like relativedelta in terms of the keyword args you
    pass in, use of the keyword n is discouraged-- you would be better
    off specifying n in the keywords you use, but regardless it is
    there for you. n is needed for DateOffset subclasses.

    DateOffets work as follows.  Each offset specify a set of dates
    that conform to the DateOffset.  For example, Bday defines this
    set to be the set of dates that are weekdays (M-F).  To test if a
    date is in the set of a DateOffset dateOffset we can use the
    onOffset method: dateOffset.onOffset(date).

    If a date is not on a valid date, the rollback and rollforward
    methods can be used to roll the date to the nearest valid date
    before/after the date.

    DateOffsets can be created to move dates forward a given number of
    valid dates.  For example, Bday(2) can be added to a date to move
    it two business days forward.  If the date does not start on a
    valid date, first it is moved to a valid date.  Thus psedo code
    is:

    def __add__(date):
      date = rollback(date) # does nothing is date is valid
      return date + <n number of periods>

    When a date offset is created for a negitive number of periods,
    the date is first rolled forward.  The pseudo code is:

    def __add__(date):
      date = rollforward(date) # does nothing is date is valid
      return date + <n number of periods>

    Zero presents a problem.  Should it roll forward or back?  We
    arbitrarily have it rollforward:

    date + BDay(0) == BDay.rollforward(date)

    Since 0 is a bit weird, we suggest avoiding its use.
    """
    # For some offsets, want to drop the time information off the
    # first date
    _normalizeFirst = False
    def __init__(self, n = 1, **kwds):
        self.n = int(n)
        self.kwds = kwds

    def apply(self, other):
        if len(self.kwds) > 0:
            if self.n > 0:
                for i in xrange(self.n):
                    other = other + relativedelta(**self.kwds)
            else:
                for i in xrange(-self.n):
                    other = other - relativedelta(**self.kwds)
            return other
        else:
            return other + timedelta(self.n)

    def isAnchored(self):
        return (self.n == 1)

    def copy(self):
        return self.__class__(self.n, **self.kwds)

    def _params(self):
        attrs = sorted((item for item in self.__dict__.iteritems()
                        if item[0] != 'kwds'))
        params = tuple([str(self.__class__)] + attrs)
        return params

    def __repr__(self):
        className = getattr(self, '_outputName', self.__class__.__name__)
        exclude = set(['n', 'inc'])
        attrs = []
        for attr in self.__dict__:
            if ((attr == 'kwds' and len(self.kwds) == 0)
                or attr.startswith('_')):
                continue
            if attr not in exclude:
                attrs.append('='.join((attr, repr(getattr(self, attr)))))
        out = '<%s ' % self.n + className + ('s' if abs(self.n) != 1 else '')
        if attrs:
            out += ': ' + ', '.join(attrs)
        out += '>'
        return out

    def __eq__(self, other):
        return self._params() == other._params()

    def __hash__(self):
        return hash(self._params())

    def __call__(self, other):
        return self.apply(other)

    def __add__(self, other):
        return self.apply(other)

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        return self.__class__(-self.n, **self.kwds) + other

    def __rsub__(self, other):
        return self.__class__(-self.n, **self.kwds) + other

    def __mul__(self, someInt):
        return self.__class__(n = someInt * self.n, **self.kwds)

    def __rmul__(self, someInt):
        return self.__class__(n = someInt * self.n, **self.kwds)

    def __neg__(self):
        return self.__class__(-self.n, **self.kwds)

    def __contains__(self, other):
        return self.onOffset(other)

    def rollback(self, someDate):
        """Roll provided date backward to next offset only if not on offset"""
        if self._normalizeFirst:
            someDate = normalize_date(someDate)

        if not self.onOffset(someDate):
            someDate = someDate - self.__class__(1, **self.kwds)
        return someDate

    def rollforward(self, someDate):
        """Roll provided date forward to next offset only if not on offset"""
        if self._normalizeFirst:
            someDate = normalize_date(someDate)

        if not self.onOffset(someDate):
            someDate = someDate + self.__class__(1, **self.kwds)
        return someDate

    @classmethod
    def onOffset(cls, someDate):
        # Default (slow) method for determining if some date is a
        # member of the DateRange generated by this offset. Subclasses
        # may have this re-implemented in a nicer way.
        obj = cls()
        return someDate == ((someDate + obj) - obj)


class BDay(DateOffset):
    """
    DateOffset subclass representing possibly n business days
    """
    _normalizeFirst = True
    _outputName = 'BusinessDay'
    def __init__(self, n=1, **kwds):
        self.n = int(n)
        self.kwds = kwds
        self.offset = kwds.get('offset', timedelta(0))
        self.normalize = kwds.get('normalize', True)

    def __repr__(self):
        className = getattr(self, '_outputName', self.__class__.__name__)
        exclude = set(['n', 'inc'])
        attrs = []

        if self.offset:
            attrs = ['offset=%s' % self.offset]

        out = '<%s ' % self.n + className + ('s' if abs(self.n) != 1 else '')
        if attrs:
            out += ': ' + ', '.join(attrs)
        out += '>'
        return out

    def isAnchored(self):
        return (self.n == 1)

    def apply(self, other):
        if isinstance(other, datetime):
            n = self.n
            if n == 0 and other.weekday() > 4:
                n = 1

            result = other

            while n != 0:
                result = result + timedelta(n/abs(n))
                if result.weekday() < 5:
                    n -= n/abs(n)

            if self.normalize:
                result = datetime(result.year, result.month, result.day)

            if self.offset:
                result = result + self.offset

            return result

        elif isinstance(other, (timedelta, Tick)):
            return BDay(self.n, offset=self.offset + other,
                        normalize=self.normalize)
        else:
            raise Exception('Only know how to combine business day with '
                            'datetime or timedelta!')
    @classmethod
    def onOffset(cls, someDate):
        return someDate.weekday() < 5


class MonthEnd(DateOffset):
    _normalizeFirst = True
    """DateOffset of one month end"""

    def apply(self, other):
        n = self.n
        __junk, nDaysInMonth = calendar.monthrange(other.year, other.month)
        if other.day != nDaysInMonth:
            other = other + relativedelta(months=-1, day=31)
            if n <= 0:
                n = n + 1
        other = other + relativedelta(months=n, day=31)
        #other = datetime(other.year, other.month, nDaysInMonth)
        return other

    @classmethod
    def onOffset(cls, someDate):
        __junk, nDaysInMonth = calendar.monthrange(someDate.year,
                                                   someDate.month)
        return someDate.day == nDaysInMonth

class BMonthEnd(DateOffset):
    """DateOffset increments between business EOM dates"""
    _outputName = 'BusinessMonthEnd'
    _normalizeFirst = True

    def isAnchored(self):
        return (self.n == 1)

    def apply(self, other):
        n = self.n

        wkday, nDaysInMonth = calendar.monthrange(other.year, other.month)
        lastBDay = nDaysInMonth - max(((wkday + nDaysInMonth - 1) % 7) - 4, 0)

        if n > 0 and not other.day >= lastBDay:
            n = n - 1
        elif n <= 0 and other.day > lastBDay:
            n = n + 1
        other = other + relativedelta(months=n, day=31)

        if other.weekday() > 4:
            other = other - BDay()
        return other


class Week(DateOffset):
    """
    dayOfWeek
    0: Mondays
    1: Tuedays
    2: Wednesdays
    3: Thursdays
    4: Fridays
    5: Saturdays
    6: Sundays
    """
    _normalizeFirst = True
    def __init__(self, n=1, **kwds):
        self.n = n
        self.dayOfWeek = kwds.get('dayOfWeek', None)

        if self.dayOfWeek is not None:
            if self.dayOfWeek < 0 or self.dayOfWeek > 6:
                raise Exception('Day must be 0<=day<=6, got %d' % self.dayOfWeek)

        self.inc = timedelta(weeks=1)
        self.kwds = kwds

    def isAnchored(self):
        return (self.n == 1 and self.dayOfWeek is not None)

    def apply(self, other):
        if self.dayOfWeek is None:
            return other + self.n * self.inc

        if self.n > 0:
            k = self.n
            otherDay = other.weekday()
            if otherDay != self.dayOfWeek:
                other = other + timedelta((self.dayOfWeek - otherDay) % 7)
                k = k - 1
            for i in xrange(k):
                other = other + self.inc
        else:
            k = self.n
            otherDay = other.weekday()
            if otherDay != self.dayOfWeek:
                other = other + timedelta((self.dayOfWeek - otherDay) % 7)
            for i in xrange(-k):
                other = other - self.inc
        return other

    def onOffset(self, someDate):
        return someDate.weekday() == self.dayOfWeek


class BQuarterEnd(DateOffset):
    """DateOffset increments between business Quarter dates
    startingMonth = 1 corresponds to dates like 1/31/2007, 4/30/2007, ...
    startingMonth = 2 corresponds to dates like 2/28/2007, 5/31/2007, ...
    startingMonth = 3 corresponds to dates like 3/30/2007, 6/29/2007, ...
    """
    _outputName = 'BusinessQuarterEnd'
    _normalizeFirst = True

    def __init__(self, n=1, **kwds):
        self.n = n
        self.startingMonth = kwds.get('startingMonth', 3)

        if self.startingMonth < 1 or self.startingMonth > 3:
            raise Exception('Start month must be 1<=day<=12, got %d'
                            % self.startingMonth)

        self.offset = BMonthEnd(3)
        self.kwds = kwds

    def isAnchored(self):
        return (self.n == 1 and self.startingMonth is not None)

    def apply(self, other):
        n = self.n

        wkday, nDaysInMonth = calendar.monthrange(other.year, other.month)
        lastBDay = nDaysInMonth - max(((wkday + nDaysInMonth - 1) % 7) - 4, 0)

        monthsToGo = 3 - ((other.month - self.startingMonth) % 3)
        if monthsToGo == 3:
            monthsToGo = 0

        if n > 0 and not (other.day >= lastBDay and monthsToGo == 0):
            n = n - 1
        elif n <= 0 and other.day > lastBDay and monthsToGo == 0:
            n = n + 1

        other = other + relativedelta(months=monthsToGo + 3*n, day=31)

        if other.weekday() > 4:
            other = other - BDay()

        return other

    def onOffset(self, someDate):
        modMonth = (someDate.month - self.startingMonth) % 3
        return BMonthEnd().onOffset(someDate) and modMonth == 0

class BYearEnd(DateOffset):
    """DateOffset increments between business EOM dates"""
    _outputName = 'BusinessYearEnd'
    _normalizeFirst = True

    def apply(self, other):
        n = self.n

        wkday, nDaysInMonth = calendar.monthrange(other.year, 12)
        lastBDay = nDaysInMonth - max(((wkday + nDaysInMonth - 1) % 7) - 4, 0)

        if n > 0 and not (other.month == 12 and other.day >= lastBDay):
            n = n - 1
        elif n <= 0 and other.month == 12 and other.day > lastBDay:
            n = n + 1

        other = other + relativedelta(years=n, month=12, day=31)

        if other.weekday() > 4:
            other = other - BDay()

        return other


class YearEnd(DateOffset):
    """DateOffset increments between calendar year ends"""
    _normalizeFirst = True

    def apply(self, other):
        n = self.n
        if other.month != 12 or other.day != 31:
            other = datetime(other.year - 1, 12, 31)
            if n <= 0:
                n = n + 1
        other = other + relativedelta(years = n)
        return other

    @classmethod
    def onOffset(cls, someDate):
        return someDate.month == 12 and someDate.day == 31


class YearBegin(DateOffset):
    """DateOffset increments between calendar year begin dates"""
    _normalizeFirst = True

    def apply(self, other):
        n = self.n
        if other.month != 1 or other.day != 1:
            other = datetime(other.year, 1, 1)
            if n <= 0:
                n = n + 1
        other = other + relativedelta(years = n, day=1)
        return other

    @classmethod
    def onOffset(cls, someDate):
        return someDate.month == 1 and someDate.day == 1

#-------------------------------------------------------------------------------
# Ticks

class Tick(DateOffset):
    pass

class Hour(Tick):
    _normalizeFirst = False
    _delta = None
    _inc = timedelta(0, 3600)

    @property
    def delta(self):
        if self._delta is None:
            self._delta = self.n * self._inc

        return self._delta

    def apply(self, other):
        return other + self.delta

class Minute(Tick):
    _normalizeFirst = False
    _delta = None
    _inc = timedelta(0, 60)

    @property
    def delta(self):
        if self._delta is None:
            self._delta = self.n * self._inc

        return self._delta

    def apply(self, other):
        return other + self.delta

class Second(Tick):
    _normalizeFirst = False
    _delta = None
    _inc = timedelta(0, 1)

    @property
    def delta(self):
        if self._delta is None:
            self._delta = self.n * self._inc

        return self._delta

    def apply(self, other):
        return other + self.delta

day = DateOffset()
bday = BDay(normalize=True)
businessDay = bday
monthEnd = MonthEnd()
yearEnd = YearEnd()
yearBegin = YearBegin()
bmonthEnd = BMonthEnd()
businessMonthEnd = bmonthEnd
bquarterEnd = BQuarterEnd()
byearEnd = BYearEnd()
week = Week()

# Functions/offsets to roll dates forward
thisMonthEnd = MonthEnd(0)
thisBMonthEnd = BMonthEnd(0)
thisYearEnd = YearEnd(0)
thisYearBegin = YearBegin(0)
thisBQuarterEnd = BQuarterEnd(0)

# Functions to check where a date lies
isBusinessDay = BDay.onOffset
isMonthEnd = MonthEnd.onOffset
isBMonthEnd = BMonthEnd.onOffset

#-------------------------------------------------------------------------------
# Offset names ("time rules") and related functions

_offsetMap = {
    "WEEKDAY"  : BDay(1),
    "EOM"      : BMonthEnd(1),
    "W@MON"    : Week(dayOfWeek=0),
    "W@TUE"    : Week(dayOfWeek=1),
    "W@WED"    : Week(dayOfWeek=2),
    "W@THU"    : Week(dayOfWeek=3),
    "W@FRI"    : Week(dayOfWeek=4),
    "Q@JAN"    : BQuarterEnd(startingMonth=1),
    "Q@FEB"    : BQuarterEnd(startingMonth=2),
    "Q@MAR"    : BQuarterEnd(startingMonth=3),
    "A@DEC"    : BYearEnd()
}

_offsetNames = dict([(v, k) for k, v in _offsetMap.iteritems()])

def inferTimeRule(index):
    if len(index) <= 1:
        raise Exception('Need at least two dates to infer time rule!')

    first, second, third = index[:3]
    for rule, offset in _offsetMap.iteritems():
        if second == (first + offset) and third == (second + offset):
            return rule

    raise Exception('Could not infer time rule from data!')

def getOffset(name):
    """
    Return DateOffset object associated with rule name

    Example
    -------
    getOffset('EOM') --> BMonthEnd(1)
    """
    offset = _offsetMap.get(name)
    if offset is not None:
        return offset
    else:
        raise Exception('Bad rule name requested: %s!' % name)

def hasOffsetName(offset):
    return offset in _offsetNames

def getOffsetName(offset):
    """
    Return rule name associated with a DateOffset object

    Example
    -------
    getOffsetName(BMonthEnd(1)) --> 'EOM'
    """
    name = _offsetNames.get(offset)
    if name is not None:
        return name
    else:
        raise Exception('Bad offset name requested: %s!' % offset)
