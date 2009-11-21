# pylint: disable-msg=E1101
# pylint: disable-msg=E1103

from datetime import datetime
import numpy as np
from pandas.core.index import Index
from pandas.lib.tseries import map_indices
import pandas.core.datetools as datetools

#-------------------------------------------------------------------------------
# XDateRange class

class XDateRange(object):
    """
    XDateRange/DateRange generate a sequence of dates corresponding to the
    specified time interval.

    Inputs:
         - toDate and/or fromDate and/or nPeriods (but not all 3)
         - offset: a DateOffset object used to determine the dates returned

    Note that if both fromDate and toDate are specified, the returned dates
    will satisfy:

    fromDate <= date <= toDate

    In other words, dates are constrained to lie in the specifed range as you
    would expect, though no dates which do NOT lie on the offset will be
    returned.

    NOTE: XDateRange is a generator, use if you do not intend to reuse the date
    range, or if you are doing lazy iteration, or if the number of dates you
    are generating is very large. If you intend to reuse the range,
    use DateRange, which will be the list of dates generated by XDateRange.
    """
    _cache = {}
    _cacheStart = {}
    _cacheEnd = {}
    def __init__(self, fromDate=None, toDate=None, nPeriods=None,
                 offset=datetools.BDay()):

        fromDate = datetools.to_datetime(fromDate)
        toDate = datetools.to_datetime(toDate)

        if fromDate and not offset.onOffset(fromDate):
            fromDate = fromDate + offset.__class__(n=1, **offset.kwds)
        if toDate and not offset.onOffset(toDate):
            toDate = toDate - offset.__class__(n=1, **offset.kwds)
            if nPeriods == None and toDate < fromDate:
                toDate = None
                nPeriods = 0

        if toDate is None:
            toDate = fromDate + (nPeriods - 1) * offset

        if fromDate is None:
            fromDate = toDate - (nPeriods - 1) * offset

        self.offset = offset
        self.fromDate = fromDate
        self.toDate = toDate
        self.nPeriods = nPeriods

    def __iter__(self):
        offset = self.offset
        cur = self.fromDate
        if offset._normalizeFirst:
            cur = datetools.normalize_date(cur)
        while cur <= self.toDate:
            yield cur
            cur = cur + offset

#-------------------------------------------------------------------------------
# DateRange cache

CACHE_START = datetime(1950, 1, 1)
CACHE_END   = datetime(2030, 1, 1)

def _getIndexLoc(index, date):
    if date in index.indexMap:
        return index.indexMap[date]
    else:
        asOf = index.asOfDate(date)
        return index.indexMap[asOf] + 1

#-------------------------------------------------------------------------------
# DateRange class

class DateRange(Index):
    """
    Fixed frequency date range according to input parameters.

    Input dates satisfy:
        begin <= d <= end, where d lies on the given offset

    Parameters
    ----------
    fromDate: {datetime, None}
        left boundary for range
    toDate: {datetime, None}
        right boundary for range
    periods: int
        Number of periods to generate.
    offset: DateOffset, default is 1 BusinessDay
        Used to determine the dates returned
    """
    _cache = {}
    def __new__(cls, fromDate=None, toDate=None, periods=None,
                offset=datetools.bday, **kwds):

        # Allow us to circumvent hitting the cache
        index = kwds.get('index')
        if index is None:
            # Cachable
            if not fromDate:
                fromDate = kwds.get('begin')
            if not toDate:
                toDate = kwds.get('end')
            if not periods:
                periods = kwds.get('nPeriods')

            if offset.isAnchored() and not isinstance(offset, datetools.Tick):
                index = cls.getCachedRange(fromDate, toDate, periods=periods,
                                           offset=offset)
            else:
                xdr = XDateRange(fromDate=fromDate, toDate=toDate,
                                 nPeriods=periods, offset=offset)

                index = np.array(list(xdr), dtype=object, copy=False)

                index = index.view(cls)
                index.offset = offset
        else:
            index = index.view(cls)

        return index

    @classmethod
    def getCachedRange(cls, start=None, end=None, periods=None, offset=None):
        if offset is None:
            raise Exception('Must provide a DateOffset!')

        start = datetools.to_datetime(start)
        end = datetools.to_datetime(end)

        if start is not None and not isinstance(start, datetime):
            raise Exception('%s is not a valid date!' % start)

        if end is not None and not isinstance(end, datetime):
            raise Exception('%s is not a valid date!' % end)

        if offset not in cls._cache:
            xdr = XDateRange(CACHE_START, CACHE_END, offset=offset)
            arr = np.array(list(xdr), dtype=object, copy=False)

            cachedRange = DateRange.fromIndex(arr)
            cachedRange.offset = offset

            cls._cache[offset] = cachedRange
        else:
            cachedRange = cls._cache[offset]

        if start is None:
            if end is None:
                raise Exception('Must provide start or end date!')
            if periods is None:
                raise Exception('Must provide number of periods!')

            if end not in cachedRange:
                endLoc = _getIndexLoc(cachedRange, end)
            else:
                endLoc = cachedRange.indexMap[end] + 1

            startLoc = endLoc - periods
        elif end is None:
            startLoc = _getIndexLoc(cachedRange, start)
            if periods is None:
                raise Exception('Must provide number of periods!')

            endLoc = startLoc + periods
        else:
            startLoc = _getIndexLoc(cachedRange, start)

            if end not in cachedRange:
                endLoc = _getIndexLoc(cachedRange, end)
            else:
                endLoc = cachedRange.indexMap[end] + 1

        indexSlice = cachedRange[startLoc:endLoc]
        indexSlice._parent = cachedRange

        return indexSlice

    @classmethod
    def fromIndex(cls, index):
        index = cls(index=index)
        return index

    def __array_finalize__(self, obj):
        if self.ndim == 0:
            return self.item()

        if len(self) > 0:
            self.indexMap = map_indices(self)
        else:
            self.indexMap = {}

        self.offset = getattr(obj, 'offset', None)
        self._parent = getattr(obj, '_parent',  None)
        self._allDates = True

    def __lt__(self, other):
        return self.view(np.ndarray) < other

    def __le__(self, other):
        return self.view(np.ndarray) <= other

    def __gt__(self, other):
        return self.view(np.ndarray) > other

    def __ge__(self, other):
        return self.view(np.ndarray) >= other

    def __eq__(self, other):
        return self.view(np.ndarray) == other

    def __getitem__(self, key):
        """Override numpy.ndarray's __getitem__ method to work as desired"""
        if isinstance(key, (int, np.int32)):
            return self.view(np.ndarray)[key]
        elif isinstance(key, slice):
            if self.offset is None:
                return Index.__getitem__(self, key)

            if key.step is not None:
                newOffset = key.step * self.offset
                newRule = None
            else:
                newOffset = self.offset
            newIndex = Index(self.view(np.ndarray)[key]).view(DateRange)
            newIndex.offset = newOffset
            return newIndex
        else:
            return Index(self.view(np.ndarray)[key])

    def __repr__(self):
        output = str(self.__class__) + '\n'
        output += 'offset: %s\n' % self.offset
        output += '[%s, ..., %s]\n' % (self[0], self[-1])
        output += 'length: %d' % len(self)
        return output

    def __str__(self):
        return self.__repr__()

    def shift(self, n):
        if n > 0:
            start = self[-1] + self.offset
            tail = DateRange(fromDate=start, periods=n)
            newArr = np.concatenate((self[n:], tail)).view(DateRange)
            newArr.offset = self.offset
            return newArr
        elif n < 0:
            end = self[0] - self.offset
            head = DateRange(toDate=end, periods=-n)

            newArr = np.concatenate((head, self[:n])).view(DateRange)
            newArr.offset = self.offset
            return newArr
        else:
            return self
