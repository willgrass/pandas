"""
Data structure for 1-dimensional cross-sectional and time series data
"""

# pylint: disable-msg=E1101
# pylint: disable-msg=E1103
# pylint: disable-msg=W0703

from itertools import izip

from numpy import NaN, ndarray
import numpy as np

from pandas.core.daterange import DateRange
from pandas.core.index import Index
from pandas.core.mixins import Picklable, Groupable
import pandas.core.datetools as datetools

from pandas.lib.tseries import isnull, notnull
import pandas.lib.tseries as tseries

#-------------------------------------------------------------------------------
# Wrapper function for Series arithmetic methods

def _seriesOpWrap(opname):
    """
    Wrapper function for Series arithmetic operations, to avoid
    code duplication.
    """
    MIRROR_OPS = {
        '__add__' : '__radd__',
        '__sub__' : '__rsub__',
        '__div__' : '__rdiv__',
        '__mul__' : '__rmul__',
    }
    def wrapper(self, other):
        from pandas.core.frame import DataFrame

        func = getattr(self.values(), opname)
        cls = self.__class__
        if isinstance(other, Series):
            if self.index.equals(other.index):
                return cls(func(other.values()), index=self.index)

            newIndex = self.index + other.index

            try:
                arr = tseries.combineFunc(opname, newIndex, self, other,
                                          self.index.indexMap,
                                          other.index.indexMap)
            except Exception:
                arr = Series.combineFunc(self, other,
                                         getattr(type(self[0]), opname))
            result = cls(arr, index=newIndex)
            return result

        elif isinstance(other, DataFrame):
            reverse_op = MIRROR_OPS.get(opname)

            if reverse_op is None:
                raise Exception('Cannot do %s op, sorry!')

            return getattr(other, reverse_op)(self)
        else:
            return cls(func(other), index=self.index)
    return wrapper

#-------------------------------------------------------------------------------
# Series class

class Series(np.ndarray, Picklable, Groupable):
    """
    Generic indexed series (time series or otherwise) object.

    Contains values in a numpy-ndarray with an optional bound index
    (also an array of dates, strings, or whatever you want the 'row
    names' of your series to be)

    Rows can be retrieved by index value (date, string, etc.) or
    relative position in the underlying array.

    Operations between Series (+, -, /, *, **) objects are
    *index-safe*, meaning that values will be combined by their
    respective index positions rather than relative positions in the
    underlying ndarray. In other words, there is no 'matching' or
    'aligning' to do, it's all taken care of for you.

    Parameters
    ----------
    data : array-like
        Underlying values of Series, preferably as numpy ndarray
    index : array-like
        Index object (or other iterable of same length as data)

    Note
    ----
    If you combine two series, all values for an index position must
    be present or the value for that index position will be nan. The
    new index is the sorted union of the two Series indices.

    Examples
    --------
        >>> s = Series(arr, index=Index(dates))
        >>> t = Series(otherArr, index=Index(otherDates))
        >>> s / t # --> new Series resulting from by-index division of elements
        >>> d = s.index[5]
        >>> s[5]
        >>> s[d]    # Valid
    """
    def __new__(cls, data, index=None, dtype=None, copy=False):
        if index is None and isinstance(data, Series):
            index = data.index

        # Make a copy of the data, infer type
        subarr = np.array(data, dtype=dtype, copy=copy)

        if subarr.ndim == 0:
            return subarr.item()

        if index is None:
            raise Exception('Index cannot be None!')

        # This is to prevent mixed-type Series getting all casted to
        # NumPy string type, e.g. NaN --> '-1#IND'.

        if issubclass(subarr.dtype.type, basestring):
            subarr = np.array(data, dtype=object, copy=copy)

        # Change the class of the array to be the subclass type.
        subarr = subarr.view(cls)
        subarr.index = index

        if subarr.index._allDates:
            subarr = subarr.view(TimeSeries)

        return subarr

    def __hash__(self):
        raise TypeError('unhashable type')

    def _get_index(self):
        return self._index

    def _set_index(self, index):
        indexTypes = ndarray, Index, list, tuple
        if not isinstance(index, indexTypes):
            raise TypeError("Expected index to be in %s; was %s."
                            % (indexTypes, type(index)))

        if len(self) != len(index):
            raise AssertionError('Lengths of index and values did not match!')

        if not isinstance(index, Index):
            index = Index(index)

        self._index = index

    _index = None
    index = property(fget=_get_index, fset=_set_index)

    def __array_finalize__(self, obj):
        """
        Gets called after any ufunc or other array operations, necessary
        to pass on the index.
        """
        self._index = getattr(obj, '_index', None)

    @classmethod
    def fromDict(cls, input, castFloat=True, **kwds):
        """
        Construct Series from dict

        Parameters
        ----------
        input : dict object
            Keys become indices of returned Series
        kwds : optionally provide arguments as keywords

        Returns
        -------
        y : Series
        """
        input = input.copy()
        input.update(kwds)

        index = Index(sorted(input.keys()))
        if castFloat:
            try:
                useData = [float(input[idx]) for idx in index]
            except Exception:
                useData = [input[idx] for idx in index]
        else:
            useData = [input[idx] for idx in index]
        return Series(useData, index=index)

    def toDict(self):
        return dict(self.iteritems())

    @classmethod
    def fromValue(cls, value=np.NaN, index=None, dtype=None):
        """
        Create Series with all values being the input scalar

        Parameters
        ----------
        input : dict object
            Keys become indices of returned Series
        kwds : optionally provide arguments as keywords

        Returns
        -------
        y : Series
        """
        # If we create an empty array using a string to infer
        # the dtype, NumPy will only allocate one character per entry
        # so this is kind of bad. Alternately we could use np.repeat
        # instead of np.empty (but then you still don't want things
        # coming out as np.str_!
        if isinstance(value, basestring):
            dtype = np.object_

        if dtype is None:
            arr = np.empty(len(index), dtype=type(value))
        else:
            arr = np.empty(len(index), dtype=dtype)
        arr.fill(value)

        return Series(arr, index=index)

    def __contains__(self, key):
        return key in self.index

    def __reduce__(self):
        """Necessary for making this object picklable"""
        object_state = list(ndarray.__reduce__(self))
        subclass_state = (self.index, )
        object_state[2] = (object_state[2], subclass_state)
        return tuple(object_state)

    def __setstate__(self, state):
        """Necessary for making this object picklable"""
        nd_state, own_state = state
        ndarray.__setstate__(self, nd_state)
        index, = own_state
        self.index = index

    def __getitem__(self, key):
        """
        Returns item(s) for requested index/sequence, overrides default behavior
        for series[key].

        Logic is as follows:
            - If key is in the index, return the value corresponding
              to that index
            - Otherwise, use key (presumably one integer or a sequence
              of integers) to obtain values from the series. In the case
              of a sequence, a 'slice' of the series (with corresponding dates)
              will be returned, otherwise a single value.
        """
        values = self.values()

        try:
            # Check that we can even look for this in the index
            return values[self.index.indexMap[key]]
        except KeyError:
            if isinstance(key, int):
                return values[key]
            raise Exception('Requested index not in this series!')
        except TypeError:
            # Could not hash item
            pass

        # is there a case where this would NOT be an ndarray?
        # need to find an example, I took out the case for now

        dataSlice = values[key]
        indices = Index(self.index.view(ndarray)[key])
        return self.__class__(dataSlice, index=indices)

    def get(self, key, missingVal=None):
        """
        Returns value occupying requested index, default to missingVal
        if not present

        Parameters
        ----------
        key : object
            Index value looking for
        missingVal : object, optional
            Value to return if key not in index

        Returns
        -------
        y : scalar
        """
        if key in self.index:
            return ndarray.__getitem__(self, self.index.indexMap[key])
        else:
            return missingVal

    def __getslice__(self, i, j):
        """
        Returns a slice of the Series.

        Note that the underlying values are COPIES.

        The reason that the getslice returns copies is that otherwise you
        will have a reference to the original series which could be
        inadvertently changed if the slice were altered (made mutable).
        """
        newArr = self.values()[i:j].copy()
        newIndex = self.index[i:j]

        return self.__class__(newArr, index=newIndex)

    def __setitem__(self, key, value):
        """
        If this series is mutable, set specified indices equal to given values.
        """
        try:
            loc = self.index.indexMap[key]
            ndarray.__setitem__(self, loc, value)
        except Exception:
            values = self.values()
            values[key] = value

    def __setslice__(self, i, j, value):
        """Set slice equal to given value(s)"""
        ndarray.__setslice__(self, i, j, value)

    def __repr__(self):
        """Clean string representation of a Series"""
        vals = self.values()
        index = self.index

        if len(index) > 500:
            head = _seriesRepr(index[:50], vals[:50])
            tail = _seriesRepr(index[-50:], vals[-50:])
            return head + '\n...\n' + tail + '\nlength: %d' % len(vals)
        else:
            return _seriesRepr(index, vals)

    def __str__(self):
        return self.__repr__()

    def __iter__(self):
        return iter(self.values())

#-------------------------------------------------------------------------------
#   Arithmetic operators

    __add__ = _seriesOpWrap('__add__')
    __sub__ = _seriesOpWrap('__sub__')
    __mul__ = _seriesOpWrap('__mul__')
    __div__ = _seriesOpWrap('__div__')
    __pow__ = _seriesOpWrap('__pow__')

    # Inplace operators
    __iadd__ = __add__
    __isub__ = __sub__
    __imul__ = __mul__
    __idiv__ = __div__
    __ipow__ = __pow__

#-------------------------------------------------------------------------------
# Overridden ndarray methods

    def count(self):
        """
        Return number of observations of Series.

        Returns
        -------
        int (# obs)
        """
        return notnull(self.values()).sum()

    def _ndarray_statistic(self, funcname):
        arr = self.values()
        retVal = getattr(arr, funcname)()

        if isnull(retVal):
            arr = remove_na(arr)
            retVal = getattr(arr, funcname)()

        return retVal

    def sum(self, axis=None, dtype=None, out=None):
        """
        Compute sum of non-null values
        """
        return self._ndarray_statistic('sum')

    def mean(self, axis=None, dtype=None, out=None):
        """
        Compute mean of non-null values
        """
        return self._ndarray_statistic('mean')

    def min(self, axis=None, out=None):
        """
        Compute minimum of non-null values
        """
        return self._ndarray_statistic('min')

    def max(self, axis=None, out=None):
        """
        Compute maximum of non-null values
        """
        return self._ndarray_statistic('max')

    def std(self, axis=None, dtype=None, out=None, ddof=1):
        """
        Compute unbiased standard deviation of non-null values
        """
        nona = remove_na(self.values())
        if len(nona) < 2:
            return NaN
        return ndarray.std(nona, axis, dtype, out, ddof)

    def var(self, axis=None, dtype=None, out=None, ddof=1):
        """
        Compute unbiased variance of non-null values
        """
        nona = remove_na(self.values())
        if len(nona) < 2:
            return NaN
        return ndarray.var(nona, axis, dtype, out, ddof)

    def skew(self, bias=False):
        """
        Computes the skewness of the non-null values

        Parameters
        ----------
        bias : bool
            If False, then the calculations are corrected for
            statistical bias.
        """

        from scipy.stats import skew
        nona = remove_na(self.values())

        if len(nona) < 3:
            return NaN

        theSkew = skew(nona, bias=bias)

        # Hack for SciPy < 0.8
        if isinstance(theSkew, ndarray):
            theSkew = theSkew.item()

        return theSkew

    def keys(self):
        """
        Return Series index
        """
        return self.index

    def values(self):
        """
        Return Series as ndarray
        """
        return self.view(ndarray)

    def iteritems(self):
        """
        Lazily iterate over (index, value) tuples
        """
        return izip(iter(self.index), iter(self))

    def append(self, other):
        """
        Concatenate two Series. The indices should not overlap

        Parameters
        ----------
        other : Series

        Returns
        -------
        y : Series
        """
        newIndex = np.concatenate((self.index, other.index))

        # Force overlap check
        try:
            newIndex = Index(newIndex)
        except Exception:
            raise

        newValues = np.concatenate((self, other))
        return self.__class__(newValues, index=newIndex)

    def combineFunc(self, other, func):
        """
        Combines this Series using the given function with either
          * another Series index by index
          * a scalar value
          * DataFrame

        Parameters
        ----------
        other : {Series, DataFrame, scalar value}

        Returns
        -------
        y : {Series or DataFrame}
            Output depends on input. If a DataFrame is inputted, that
            will be the return type.
        """
        if isinstance(other, Series):
            newIndex = self.index + other.index

            newArr = np.empty(len(newIndex), dtype=self.dtype)
            for i, idx in enumerate(newIndex):
                newArr[i] = func(self.get(idx, NaN), other.get(idx, NaN))
        else:
            newIndex = self.index
            newArr = func(self.values(), other)

        return self.__class__(newArr, index=newIndex)

    def combineFirst(self, other):
        """
        Combine Series values, choosing calling Series's values first.

        Parameters
        ----------
        other : Series

        Returns
        -------
        y : Series
            formed as union of two Series
        """
        newIndex = self.index + other.index

        this = self
        if newIndex is not self.index:
            # save ourselves the copying in this case

            this = self.reindex(newIndex)
            other = other.reindex(newIndex)

        result = Series(np.where(isnull(this), other, this), index=newIndex)
        return result

    def argsort(self, axis=0, kind='quicksort', order=None):
        """
        Overriding numpy's built-in cumsum functionality
        """
        arr = self.values().copy()
        okLocs = notnull(arr)
        arr[okLocs] = np.argsort(arr[okLocs])
        return self.__class__(arr, index=self.index)

    def cumsum(self, axis=0, dtype=None, out=None):
        """
        Overriding numpy's built-in cumsum functionality
        """
        arr = self.copy()
        okLocs = notnull(arr)
        result = np.cumsum(arr.view(ndarray)[okLocs])
        arr = arr.astype(result.dtype)
        arr[okLocs] = result
        return arr

    def cumprod(self, axis=0, dtype=None, out=None):
        """
        Overriding numpy's built-in cumprod functionality
        """
        arr = self.copy()
        okLocs = notnull(arr)
        arr[okLocs] = np.cumprod(arr.view(ndarray)[okLocs])
        return arr

    def median(self):
        """
        Compute median value of non-null values
        """
        return tseries.median(self.valid())

    def copy(self):
        return self.__class__(self.values().copy(), index=self.index)

    def corr(self, other):
        """
        Compute correlation two Series, excluding missing values

        Parameters
        ----------
        other : Series object

        Returns
        -------
        correlation : float
        """
        commonIdx = remove_na(self).index.intersection(remove_na(other).index)

        if len(commonIdx) == 0:
            return NaN

        this = self.reindex(commonIdx)
        that = other.reindex(commonIdx)

        return np.corrcoef(this, that)[0, 1]

    def sort(self, axis=0, kind='quicksort', order=None):
        """
        Overridden NumPy sort, taking care with missing values
        """
        sortedSeries = self.order(missingAtEnd=True)
        self[:] = sortedSeries
        self.index = sortedSeries.index

    def order(self, missingAtEnd=True):
        """
        Sorts Series object, by value, maintaining index-value object

        Parameters
        ----------
        missingAtEnd : boolean (optional, default=True)
            Put NaN's at beginning or end

        In general, AVOID sorting Series unless you absolutely need to.

        Returns
        -------
        y : Series
            sorted by values
        """
        arr = self.values()
        sortedIdx = np.empty(len(self), dtype=np.int32)

        bad = isnull(arr)

        good = -bad
        idx = np.arange(len(self))
        if missingAtEnd:
            n = sum(good)
            sortedIdx[:n] = idx[good][arr[good].argsort()]
            sortedIdx[n:] = idx[bad]
        else:
            n = sum(bad)
            sortedIdx[n:] = idx[good][arr[good].argsort()]
            sortedIdx[:n] = idx[bad]

        return Series(arr[sortedIdx], index=self.index[sortedIdx])

    def map(self, func):
        """
        Apply input Python function element-wise to each element of
        Series.

        Parameters
        ----------
        func : function
            Element-wise function to apply

        Returns
        -------
        y : Series
            same index as caller
        """
        return Series([func(x) for x in self], index=self.index)

    def plot(self, label=None, kind='line', **kwds): # pragma: no cover
        """
        Plot the input series with the index on the x-axis using
        matplotlib / pylab.

        Parameters
        ----------
        label : label argument to provide to plot

        kind : {'line', 'bar', 'hist'}
            Default: line for TimeSeries, hist for Series

        kwds : other plotting keyword arguments

        Default plot-types:
            TimeSeries: line chart
            Series: histogram
                Also support for bar charts

        Type show() (make sure to do 'from pylab import *') to see graph if you
        do not.

        Note
        ----
        See matplotlib documentation online for more on this subject
        """
        import pylab

        if label is not None:
            kwds = kwds.copy()
            kwds['label'] = label

        pylab.plot(self.index, self, **kwds)

    def toCSV(self, path):
        """
        Write the Series to a CSV file

        Parameters
        ----------
        path : string or None
            Output filepath. If None, write to stdout
        """
        f = open(path, 'wb')

        for idx, value in self.iteritems():
            f.write(str(idx) + ',' + str(value) + ',\n')

        f.close()

    def cap(self, value):
        """Return copy of series with values above given value truncated"""
        myCopy = self.copy()
        myCopy[notnull(myCopy) & (myCopy > value)] = value
        return myCopy

    def floor(self, value):
        """Return copy of series with values BELOW given value truncated"""
        myCopy = self.copy()
        myCopy[notnull(myCopy) & (myCopy < value)] = value
        return myCopy

    def valid(self):
        """
        Return Series without NaN values

        Returns
        -------
        Series
        """
        return remove_na(self)

    def _firstTimeWithValue(self):
        noNA = remove_na(self)

        if len(noNA) > 0:
            return noNA.index[0]
        else:
            return None

    def _lastTimeWithValue(self):
        noNA = remove_na(self)

        if len(noNA) > 0:
            return noNA.index[-1]
        else:
            return None

#-------------------------------------------------------------------------------
# TimeSeries methods

    def shift(self, periods, offset=None, timeRule=None):
        """
        Shift the underlying series of the DataMatrix and Series objects within
        by given number (positive or negative) of business/weekdays.

        Parameters
        ----------
        periods : int (+ or -)
            Number of periods to move
        offset : DateOffset, optional
            Increment to use from datetools module
        timeRule : string
            time rule name to use by name (e.g. 'WEEKDAY')

        Returns
        -------
        TimeSeries
        """
        if periods == 0:
            return self

        if timeRule is not None and offset is None:
            offset = datetools.getOffset(timeRule)

        if offset is None:
            newValues = np.empty(len(self), dtype=self.dtype)

            if periods > 0:
                newValues[periods:] = self.values()[:-periods]
                newValues[:periods] = np.NaN
            elif periods < 0:
                newValues[:periods] = self.values()[-periods:]
                newValues[periods:] = np.NaN
            else:
                newValues = self.values().copy()

            return self.__class__(newValues, index=self.index)
        else:
            offset = periods * offset
            newIndex = Index([idx + offset for idx in self.index])

            return self.__class__(self, index=newIndex)

    def truncate(self, before=None, after=None):
        """Function truncate a sorted TimeSeries before and/or after
        some particular dates.

        Parameters
        ----------
        before : date
            Truncate before date
        after : date
            Truncate after date

        Note
        ----
        If TimeSeries is contained in a DataFrame, consider using the version
        of the function there.

        Returns
        -------
        TimeSeries
        """
        before = arg_before = datetools.to_datetime(before)
        after = arg_after = datetools.to_datetime(after)

        if before is None:
            before = self.index[0]
        elif before not in self.index:
            loc = self.index.searchsorted(before, side='left')
            before = self.index[loc]

        if after is None:
            after = self.index[-1]
        elif after not in self.index:
            loc = self.index.searchsorted(after, side='right') - 1
            loc = loc if loc < len(self.index) else -1
            after = self.index[loc]

        beg_slice = self.index.indexMap[before]
        end_slice = self.index.indexMap[after] + 1

        return self[beg_slice:end_slice]

    def slice(self, before, after):
        return self.truncate(before=before, after=after)

    def asOf(self, date):
        """
        Return last good (non-NaN) value in TimeSeries if value is NaN for
        requested date.

        If there is no good value, NaN is returned.

        Returns
        -------
        value or NaN
        """
        if isinstance(date, basestring):
            date = datetools.to_datetime(date)

        v = self.get(date)

        if isnull(v):
            candidates = self.index[notnull(self)]
            candidates = candidates[candidates <= date]

            if any(candidates):
                asOfDate = max(candidates)
            else:
                return NaN

            return self.get(asOfDate)
        else:
            return v

    def fill(self, value=None, method='pad'):
        """
        Fill NaN values using the specified method.

        Parameters
        ----------
        value : any kind (should be same type as array)
            Value to use to fill holes (e.g. 0)

        method : {'backfill', 'pad', None}
            Method to use for filling holes in new inde

        Returns
        -------
        TimeSeries with NaN's filled

        See also
        --------
        reindex, asfreq
        """
        if value is not None:
            newSeries = self.copy()
            newSeries[isnull(newSeries)] = value
            return newSeries
        else: # Using reindex to pad / backfill
            withoutna = remove_na(self)
            return withoutna.reindex(self.index, fillMethod=method)

    def asfreq(self, freq, fillMethod=None):
        """
        Convert this TimeSeries to the provided frequency using DateOffset
        objects. Optionally provide fill method to pad/backfill/interpolate
        missing values.

        Parameters
        ----------
        offset : DateOffset object, or string in {'WEEKDAY', 'EOM'}
            DateOffset object or subclass (e.g. monthEnd)

        fillMethod : {'backfill', 'pad', 'interpolate', None}
                    Method to use for filling holes in new inde

        Returns
        -------
        TimeSeries
        """
        if isinstance(freq, datetools.DateOffset):
            dateRange = DateRange(self.index[0], self.index[-1], offset=freq)
        else:
            dateRange = DateRange(self.index[0], self.index[-1], timeRule=freq)

        return self.reindex(dateRange, fillMethod=fillMethod)

    def interpolate(self, method='linear'):
        """
        Interpolate missing values (after the first valid value)

        Parameters
        ----------
        method : {'linear', 'time'}
            Interpolation method.

            Time interpolation works on daily and higher resolution
            data to interpolate given length of interval

        Returns
        -------
        Series with values interpolated
        """
        if method == 'time':
            if not isinstance(self, TimeSeries):
                raise Exception('time-weighted interpolation only works'
                                'on TimeSeries')
            inds = np.array([d.toordinal() for d in self.index])
        else:
            inds = np.arange(len(self))

        values = self.values()

        invalid = isnull(values)
        valid = -invalid

        firstIndex = valid.argmax()
        valid = valid[firstIndex:]
        invalid = invalid[firstIndex:]
        inds = inds[firstIndex:]

        result = values.copy()
        result[firstIndex:][invalid] = np.interp(inds[invalid], inds[valid],
                                                 values[firstIndex:][valid])

        return Series(result, index=self.index)

    def merge(self, other):
        """
        If self is {A}->{B} and other is another mapping of {B}->{C}
        then returns a new Series that is {A}->{C}

        Parameters
        ----------
        other : dict or Series

        Returns
        -------
        Series having same index as calling instance, with values from
        input Series
        """
        if isinstance(other, dict):
            other = Series.fromDict(other)

        if not isinstance(other, Series):
            raise Exception('Argument must be a Series!')

        fillVec, mask = tseries.getMergeVec(self, other.index.indexMap)

        newValues = other.view(np.ndarray).take(fillVec)
        newValues[-mask] = np.nan

        newSer = Series(newValues, index=self.index)
        return newSer

    def reindex(self, newIndex, fillMethod=None):
        """Overloaded version of reindex for TimeSeries. Supports filling
        with values based on new index.

        See analogous method for DataFrame, will be faster for multiple
        TimeSeries

        Parameters
        ----------
        newIndex :   array-like, preferably an Index object (to avoid
                    duplicating data)
        fillMethod : {'backfill', 'pad', 'interpolate', None}
                    Method to use for filling holes in reindexed Series

        Returns
        -------
        TimeSeries
        """
        if fillMethod is None:
            if self.index is newIndex:
                return self.copy()

            if not isinstance(newIndex, Index):
                newIndex = Index(newIndex)

            idxMap = self.index.indexMap

            if self.dtype == float:
                vals = tseries.reindex(newIndex, self, idxMap)
            elif self.dtype == int:
                # This could be unsafe, but NaN will not work in int arrays.
                vals = tseries.reindex(newIndex, self.astype(float), idxMap)
            else:
                if self.dtype.type == np.object_:
                    vals = tseries.reindexObj(newIndex, self, idxMap)
                else:
                    thisVals = self.values().astype(object)
                    vals = tseries.reindexObj(newIndex, thisVals, idxMap)

                    if not isnull(vals).any():
                        vals = vals.astype(self.dtype)

            return self.__class__(vals, index=newIndex)

        if not isinstance(newIndex, Index):
            newIndex = Index(newIndex)

        if len(self.index) == 0:
            return self.__class__.fromValue(NaN, index=newIndex)

        oldMap = self.index.indexMap
        newMap = newIndex.indexMap

        if not fillMethod:
            fillMethod = ''

        fillMethod = fillMethod.upper()

        if fillMethod not in ['BACKFILL', 'PAD', '']:
            raise Exception("Don't recognize fillMethod: %s" % fillMethod)

        # Cython for blazing speed
        fillVec, mask = tseries.getFillVec(self.index, newIndex, oldMap,
                                           newMap, kind=fillMethod)

        newValues = self.values().take(fillVec)
        newValues[-mask] = NaN

        return self.__class__(newValues, index=newIndex)

    @property
    def weekday(self):
        return self.__class__([d.weekday() for d in self.index],
                              index = self.index)

    def diff(self):
        """
        1st discrete difference of object

        Returns
        -------
        TimeSeries
        """
        return (self - self.shift(1))

    def autocorr(self):
        """
        1st period autocorrelation coefficient

        Returns
        -------
        TimeSeries
        """
        return self.corr(self.shift(1))


class TimeSeries(Series):
    pass

#-------------------------------------------------------------------------------
# Supplementary functions

def remove_na(arr):
    """
    Return array containing only true/non-NaN values, possibly empty.
    """
    return arr[notnull(arr)]

def _seriesRepr(index, vals):
    maxlen = max([len(str(idx)) for idx in index])
    padSpace = min(maxlen, 60)
    return '\n'.join([str(x).ljust(padSpace) + '\t' + str(v)
                      for x, v in izip(index, vals)])
