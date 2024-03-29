"""
Contains data structures designed for manipulating panel (3-dimensional) data
"""
# pylint: disable-msg=E1103
# pylint: disable-msg=W0231
# pylint: disable-msg=W0212
# pylint: disable-msg=W0621

import operator
import sys

import numpy as np

from pandas.core.groupby import GroupBy
from pandas.core.index import Index
from pandas.core.frame import DataFrame
from pandas.core.matrix import DataMatrix
from pandas.core.mixins import Picklable
import pandas.core.common as common
import pandas.lib.tseries as tseries

class PanelError(Exception):
    pass

def _arith_method(func, name):
    # work only for scalars

    def f(self, other):
        if not np.isscalar(other):
            raise Exception('Simple arithmetic with WidePanel can only be '
                            'done with scalar values')

        return self._combine(other, func)

    return f

def _long_arith_method(op, name):
    def f(self, other, axis='items'):
        """
        Wrapper method for %s

        Parameters
        ----------
        other : DataFrame or Panel class
        axis : {'items', 'major', 'minor'}

        Returns
        -------
        LongPanel
        """
        return self._combine(other, op, axis=axis)

    f.__name__ = name
    f.__doc__ = f.__doc__ % str(op)

    return f

def _wide_arith_method(op, name):
    def f(self, other, axis='items'):
        """
        Wrapper method for %s

        Parameters
        ----------
        other : DataFrame or Panel class
        axis : {'items', 'major', 'minor'}

        Returns
        -------
        WidePanel
        """
        return self._combine(other, op, axis=axis)

    f.__name__ = name
    f.__doc__ = f.__doc__ % str(op)

    return f

class PanelAxis(object):

    def __init__(self, cache_field):
        self.cache_field = cache_field

    def __get__(self, obj, type=None):
        return getattr(obj, self.cache_field)

    def __set__(self, obj, value):
        if not isinstance(value, Index):
            value = Index(value)

        setattr(obj, self.cache_field, value)

class Panel(Picklable):
    """
    Abstract superclass for LongPanel and WidePanel data structures
    """
    _values = None
    factors = None

    __add__ = _arith_method(operator.add, '__add__')
    __sub__ = _arith_method(operator.sub, '__sub__')
    __mul__ = _arith_method(operator.mul, '__mul__')
    __div__ = _arith_method(operator.div, '__div__')
    __pow__ = _arith_method(operator.pow, '__pow__')

    __radd__ = _arith_method(operator.add, '__radd__')
    __rmul__ = _arith_method(operator.mul, '__rmul__')
    __rsub__ = _arith_method(lambda x, y: y - x, '__rsub__')
    __rdiv__ = _arith_method(lambda x, y: y / x, '__rdiv__')
    __rpow__ = _arith_method(lambda x, y: y ** x, '__rpow__')

    items = PanelAxis('_items')
    major_axis = PanelAxis('_major_axis')
    minor_axis = PanelAxis('_minor_axis')

    def __repr__(self):
        class_name = str(self.__class__)

        I, N, K = len(self.items), len(self.major_axis), len(self.minor_axis)

        dims = 'Dimensions: %d (items) x %d (major) x %d (minor)' % (I, N, K)

        major = 'Major axis: %s to %s' % (self.major_axis[0],
                                          self.major_axis[-1])

        minor = 'Minor axis: %s to %s' % (self.minor_axis[0],
                                          self.minor_axis[-1])

        if len(self.items) > 0:
            items = 'Items: %s to %s' % (self.items[0], self.items[-1])
        else:
            items = 'Items: None'

        output = '%s\n%s\n%s\n%s\n%s' % (class_name, dims, items, major, minor)

        if self.factors:
            output += '\nFactors: %s' % ', '.join(self.factors)

        return output

    def __iter__(self):
        return iter(self.items)

    def iteritems(self):
        for item in self:
            yield item, self[item]

    @property
    def dims(self):
        return len(self.items), len(self.major_axis), len(self.minor_axis)

_WIDE_AXIS_NUMBERS = {
    'items' : 0,
    'major' : 1,
    'minor' : 2
}

_WIDE_AXIS_NAMES = dict((v, k) for k, v in _WIDE_AXIS_NUMBERS.iteritems())


class WidePanel(Panel):
    """
    Represents wide format panel data, stored as 3-dimensional array

    Parameters
    ----------
    values : ndarray (items x major x minor)
    items : sequence
    major_axis : sequence
    minor_axis : sequence
    """
    def __init__(self, values, items, major_axis, minor_axis):
        self.items = items
        self.major_axis = major_axis
        self.minor_axis = minor_axis

#        self.factors = factors or {}
        self.factors = {}
        self.values = values

    @classmethod
    def _get_axis_number(cls, axis):
        if axis in (0, 1, 2):
            return axis
        else:
            return _WIDE_AXIS_NUMBERS[axis]

    @classmethod
    def _get_axis_name(cls, axis):
        if axis in _WIDE_AXIS_NUMBERS:
            return axis
        else:
            return _WIDE_AXIS_NAMES[axis]

    def _get_axis(self, axis):
        results = {
            0 : self.items,
            1 : self.major_axis,
            2 : self.minor_axis
        }

        return results[self._get_axis_number(axis)]

    def _get_plane_axes(self, axis):
        """

        """
        axis = self._get_axis_name(axis)

        if axis == 'major':
            index = self.minor_axis
            columns = self.items
        if axis == 'minor':
            index = self.major_axis
            columns = self.items
        elif axis == 'items':
            index = self.major_axis
            columns = self.minor_axis

        return index, columns

    def copy(self):
        """
        Return a copy of WidePanel (only values ndarray copied)

        Returns
        -------
        y : WidePanel
        """
        return WidePanel(self.values.copy(), self.items, self.major_axis,
                         self.minor_axis)

    @classmethod
    def fromDict(cls, data, intersect=False, dtype=float):
        """
        Construct WidePanel from dict of DataFrame objects

        Parameters
        ----------
        data : dict
            {field : DataFrame}
        intersect : boolean

        Returns
        -------
        WidePanel
        """
        data, index, columns = _homogenize(data, intersect=intersect)
        items = Index(sorted(data.keys()))

        values = np.array([data[k].values for k in items], dtype=dtype)

        return cls(values, items, index, columns)

    def keys(self):
        return list(self.items)

    def _get_values(self):
        return self._values

    def _set_values(self, values):
        if not values.flags.contiguous:
            values = values.copy()

        if self.dims != values.shape:
            raise PanelError('Values shape %s did not match axes / items %s' %
                             (values.shape, self.dims))

        self._values = values

    values = property(fget=_get_values, fset=_set_values)

    def __getitem__(self, key):
        try:
            loc = self.items.indexMap[key]
        except KeyError:
            raise KeyError('%s not contained in panel data items!' % key)

        mat = self.values[loc]

        return DataMatrix(mat, index=self.major_axis, columns=self.minor_axis)

    def __delitem__(self, key):
        try:
            loc = self.items.indexMap[key]
        except KeyError:
            raise KeyError('%s not contained in panel data items!' % key)

        indices = range(loc) + range(loc + 1, len(self.items))
        self.items = self.items[indices]
        self.values = self.values.take(indices, axis=0)

    def pop(self, key):
        """
        Return item slice from panel and delete from panel

        Parameters
        ----------
        key : object
            Must be contained in panel's items

        Returns
        -------
        y : DataMatrix
        """
        result = self[key]
        del self[key]
        return result

    def __setitem__(self, key, value):
        _, N, K = self.dims

        # XXX
        if isinstance(value, LongPanel):
            if len(value.items) != 1:
                raise Exception('Input panel must have only one item!')

            value = value.toWide()[value.items[0]]

        if isinstance(value, DataFrame):
            value = value.reindex(index=self.major_axis,
                                  columns=self.minor_axis)

            mat = value.values.reshape((1, N, K))

        elif np.isscalar(value):
            mat = np.empty((1, N, K), dtype=float)
            mat.fill(value)

        if key in self.items:
            loc = self.items.indexMap[key]
            self.values[loc] = mat
        else:
            self.items = Index(list(self.items) + [key])

            # Insert item at end of items for now
            self.values = np.row_stack((self.values, mat))

    def __getstate__(self):
        "Returned pickled representation of the panel"
        _pickle = common._pickle_array

        return (_pickle(self.values), _pickle(self.items),
                _pickle(self.major_axis), _pickle(self.minor_axis))

    def __setstate__(self, state):
        "Unpickle the panel"
        _unpickle = common._unpickle_array
        vals, items, major, minor = state

        self.items = _unpickle(items)
        self.major_axis = _unpickle(major)
        self.minor_axis = _unpickle(minor)
        self.values = _unpickle(vals)

    def conform(self, frame, axis='items'):
        """
        Conform input DataFrame to align with chosen axis pair.

        Parameters
        ----------
        frame : DataFrame
        axis : {'items', 'major', 'minor'}
            Axis the input corresponds to. E.g., if axis='major', then
            the frame's columns would be items, and the index would be
            values of the minor axis

        Returns
        -------
        DataFrame (or DataMatrix)
        """
        index, columns = self._get_plane_axes(axis)

        return frame.reindex(index=index, columns=columns)

    def reindex(self, major=None, items=None, minor=None, fill_method=None):
        """
        Conform panel to new axis or axes

        Parameters
        ----------
        major : Index or sequence, default None
        items : Index or sequence, default None
        minor : Index or sequence, default None
        fill_method : {'backfill', 'pad', 'interpolate', None}
            Method to use for filling holes in reindexed panel

        Returns
        -------
        WidePanel (new object)
        """
        result = self

        if major is not None:
            result = result._reindex_axis(major, fill_method, 1)

        if minor is not None:
            result = result._reindex_axis(minor, fill_method, 2)

        if items is not None:
            result = result._reindex_axis(items, fill_method, 0)

        if result is self:
            raise Exception('Must specify at least one axis')

        return result

    def _reindex_axis(self, new_index, fill_method, axis):
        old_index = self._get_axis(axis)

        if old_index.equals(new_index):
            return self.copy()

        if not isinstance(new_index, Index):
            new_index = Index(new_index)

        indexer, mask = common.get_indexer(old_index, new_index, fill_method)

        new_values = self.values.take(indexer, axis=axis)
        common.null_out_axis(new_values, -mask, axis)

        new_axes = [self._get_axis(i) for i in range(3)]
        new_axes[axis] = new_index

        return WidePanel(new_values, *new_axes)

    def _combine(self, other, func, axis=0):
        if isinstance(other, DataFrame):
            return self._combineFrame(other, func, axis=axis)
        elif isinstance(other, Panel):
            return self._combinePanel(other, func)
        elif np.isscalar(other):
            newValues = func(self.values, other)

            return WidePanel(newValues, self.items, self.major_axis,
                             self.minor_axis)

    def __neg__(self):
        return WidePanel(-self.values, self.items, self.major_axis,
                          self.minor_axis)

    def _combineFrame(self, other, func, axis=0):
        index, columns = self._get_plane_axes(axis)
        axis = self._get_axis_number(axis)

        other = other.reindex(index=index, columns=columns)

        if axis == 0:
            newValues = func(self.values, other.values)
        elif axis == 1:
            newValues = func(self.values.swapaxes(0, 1), other.values.T)
            newValues = newValues.swapaxes(0, 1)
        elif axis == 2:
            newValues = func(self.values.swapaxes(0, 2), other.values)
            newValues = newValues.swapaxes(0, 2)

        return WidePanel(newValues, self.items, self.major_axis,
                         self.minor_axis)

    def fill(self, value=None, method='pad'):
        """
        Fill NaN values using the specified method.

        Member Series / TimeSeries are filled separately.

        Parameters
        ----------
        value : any kind (should be same type as array)
            Value to use to fill holes (e.g. 0)

        method : {'backfill', 'pad', None}
            Method to use for filling holes in new inde

        Returns
        -------
        y : DataMatrix

        See also
        --------
        DataMatrix.reindex, DataMatrix.asfreq
        """
        if value is None:
            result = {}
            for col, s in self.iteritems():
                result[col] = s.fill(method=method, value=value)

            return WidePanel.fromDict(result)
        else:
            # Float type values
            vals = self.values.copy()
            vals.flat[common.isnull(vals.ravel())] = value

            return WidePanel(vals, self.items, self.major_axis,
                             self.minor_axis)

    def _combinePanel(self, other, func):
        if isinstance(other, LongPanel):
            other = other.toWide()

        items = self.items + other.items
        major = self.major_axis + other.major_axis
        minor = self.minor_axis + other.minor_axis

        # could check that everything's the same size, but forget it

        this = self.reindex(items=items, major=major, minor=minor)
        other = other.reindex(items=items, major=major, minor=minor)

        result_values = func(this.values, other.values)

        return WidePanel(result_values, items, major, minor)

    add = _wide_arith_method(operator.add, 'add')
    subtract = _wide_arith_method(operator.sub, 'subtract')
    divide = _wide_arith_method(operator.div, 'divide')
    multiply = _wide_arith_method(operator.mul, 'multiply')

    def getMajorXS(self, key):
        """
        Parameters
        ----------

        Returns
        -------
        y : DataMatrix
            index -> minor axis, columns -> items
        """
        try:
            loc = self.major_axis.indexMap[key]
        except KeyError:
            raise KeyError('%s not contained in major axis!' % key)

        mat = np.array(self.values[:, loc, :].T)
        return DataMatrix(mat, index=self.minor_axis, columns=self.items)

    def getMinorXS(self, key):
        """
        Parameters
        ----------

        Returns
        -------
        y : DataMatrix
            index -> major axis, columns -> items
        """
        try:
            loc = self.minor_axis.indexMap[key]
        except KeyError:
            raise KeyError('%s not contained in minor axis!' % key)

        mat = np.array(self.values[:, :, loc].T)
        return DataMatrix(mat, index=self.major_axis, columns=self.items)

    def groupby(self, function, axis='major'):
        """
        Parameters
        ----------
        function : callable
            Mapping function for chosen access
        axis : {'major', 'minor', 'items'}, default 'major'

        Returns
        -------
        WidePanelGroupBy
        """
        axis = self._get_axis_number(axis)
        return WidePanelGroupBy(self, function, axis=axis)

    def swapaxes(self, axis1='major', axis2='minor'):
        """
        Interchange axes and swap values axes appropriately

        Returns
        -------
        y : WidePanel (new object)
        """
        i = self._get_axis_number(axis1)
        j = self._get_axis_number(axis2)

        if i == j:
            raise Exception('Cannot specify the same axis')

        mapping = {i : j, j : i}

        new_axes = (self._get_axis(mapping.get(k, k))
                    for k in range(3))
        new_values = self.values.swapaxes(i, j).copy()

        return WidePanel(new_values, *new_axes)

    def toLong(self, filter_observations=True):
        """
        Transform wide format into long (stacked) format

        Parameters
        ----------
        filter_observations : boolean, default True
            Drop (major, minor) pairs without a complete set of observations
            across all the items

        Returns
        -------
        y : LongPanel
        """
        I, N, K = self.dims

        if filter_observations:
            mask = np.isfinite(self.values).all(axis=0)
            size = mask.sum()
            selector = mask.ravel()
        else:
            size = N * K
            selector = slice(None, None)

        values = np.empty((size, I), dtype=float)

        for i in xrange(len(self.items)):
            values[:, i] = self.values[i].ravel()[selector]

        major_labels = np.arange(N).repeat(K)[selector]

        # Anyone think of a better way to do this? np.repeat does not
        # do what I want
        minor_labels = np.arange(K).reshape(1, K)[np.zeros(N, dtype=int)]
        minor_labels = minor_labels.ravel()[selector]

        if filter_observations:
            mask = selector
        else:
            mask = None

        index = LongPanelIndex(self.major_axis,
                               self.minor_axis,
                               major_labels,
                               minor_labels,
                               mask=mask)

        return LongPanel(values, self.items, index)

    def filter(self, items):
        """
        Restrict items in panel to input list

        Parameters
        ----------
        items : sequence

        Returns
        -------
        y : WidePanel
        """
        intersection = self.items.intersection(items)
        indexer = [self.items.indexMap[col] for col in intersection]

        new_values = self.values.take(indexer, axis=0)
        return WidePanel(new_values, intersection, self.major_axis,
                         self.minor_axis)

    def apply(self, func, axis='major'):
        """
        Apply

        Parameters
        ----------
        func : numpy function
            Signature should match numpy.{sum, mean, var, std} etc.
        axis : {'major', 'minor', 'items'}
        fill_value : boolean, default True
            Replace NaN values with specified first

        Returns
        -------
        result : DataMatrix or WidePanel
        """
        i = self._get_axis_number(axis)

        result = np.apply_along_axis(func, i, self.values)

        return self._wrap_result(result, axis=axis)

    def _values_aggregate(self, func, axis, fill_value):
        axis = self._get_axis_number(axis)

        values = self.values
        mask = np.isfinite(values)

        if fill_value is not None:
            values = values.copy()
            values[-mask] = fill_value

        result = func(values, axis=axis)
        count = mask.sum(axis=axis)

        result[count == 0] = np.NaN

        return result

    def _values_accum(self, func, axis, fill_value):
        axis = self._get_axis_number(axis)

        values = self.values
        mask = np.isfinite(values)

        if fill_value is not None:
            values = values.copy()
            values[-mask] = fill_value

        result = func(values, axis=axis)

        if fill_value is not None:
            result[-mask] = np.NaN

        return result

    def _array_method(self, func, axis='major', fill_value=None):
        """
        Parameters
        ----------
        func : numpy function
            Signature should match numpy.{sum, mean, var, std} etc.
        axis : {'major', 'minor', 'items'}
        fill_value : boolean, default True
            Replace NaN values with specified first

        Returns
        -------
        y : DataMatrix
        """
        result = self._values_aggregate(func, axis, fill_value)
        return self._wrap_result(result, axis=axis)

    def _wrap_result(self, result, axis):
        axis = self._get_axis_name(axis)

        if result.ndim == 2:
            index, columns = self._get_plane_axes(axis)

            if axis != 'items':
                result = result.T

            return DataMatrix(result, index=index, columns=columns)
        else:
            return WidePanel(result, self.items, self.major_axis,
                             self.minor_axis)

    def count(self, axis='major'):
        """
        Return DataMatrix of observation counts along desired axis

        Returns
        -------
        y : DataMatrix
        """
        i = self._get_axis_number(axis)

        values = self.values
        mask = np.isfinite(values)
        result = mask.sum(axis=i)

        return self._wrap_result(result, axis)

    def sum(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        return self._array_method(np.sum, axis=axis, fill_value=0)

    def cumsum(self, axis='major'):
        """

        Returns
        -------
        y : WidePanel
        """
        result = self._values_accum(np.cumsum, axis=axis, fill_value=0)
        return self._wrap_result(result, axis)

    def mean(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        return self.sum(axis=axis) / self.count(axis=axis)

    def var(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        i = self._get_axis_number(axis)
        index, columns = self._get_plane_axes(axis)

        y = np.array(self.values)
        mask = np.isnan(y)

        count = (-mask).sum(axis=i).astype(float)
        y[mask] = 0

        X = y.sum(axis=i)
        XX = (y ** 2).sum(axis=i)

        theVar = (XX - X**2 / count) / (count - 1)

        return self._wrap_result(theVar, axis)

    def std(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        return self.var(axis=axis).apply(np.sqrt)

    def skew(self, axis='major'):
        raise NotImplementedError

    def prod(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        return self._array_method(np.prod, axis=axis, fill_value=1)

    def compound(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        return (1 + self).prod(axis=axis) - 1

    def median(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        def f(arr):
            return tseries.median(arr[common.notnull(arr)])

        return self.apply(f, axis=axis)

    def max(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        i = self._get_axis_number(axis)

        y = np.array(self.values)
        mask = np.isfinite(y)

        fill_value = y.flat[mask.ravel()].min() - 1

        y[-mask] = fill_value

        result = y.max(axis=i)
        result[result == fill_value] = np.NaN

        return self._wrap_result(result, axis)

    def min(self, axis='major'):
        """

        Returns
        -------
        y : DataMatrix
        """
        i = self._get_axis_number(axis)

        y = np.array(self.values)
        mask = np.isfinite(y)

        fill_value = y.flat[mask.ravel()].max() + 1

        y[-mask] = fill_value

        result = y.min(axis=i)
        result[result == fill_value] = np.NaN

        return self._wrap_result(result, axis)

    def shift(self, lags, axis='major'):
        """

        Returns
        -------
        y : WidePanel
        """
        values = self.values
        items = self.items
        major_axis = self.major_axis
        minor_axis = self.minor_axis

        if axis == 'major':
            values = values[:, :-lags, :]
            major_axis = major_axis[lags:]
        elif axis == 'minor':
            values = values[:, :, :-lags]
            minor_axis = minor_axis[lags:]
        else:
            raise Exception('Invalid axis')

        return WidePanel(values=values, items=items, major_axis=major_axis,
                         minor_axis=minor_axis)


    def truncate(self, before=None, after=None, axis='major'):
        """Function truncates a sorted Panel before and/or after
        some particular dates

        Parameters
        ----------
        before : date
            Left boundary
        after : date
            Right boundary

        Returns
        -------
        WidePanel
        """
        axis = self._get_axis_name(axis)
        index = self._get_axis(axis)

        beg_slice, end_slice = self._getIndices(before, after, axis=axis)
        new_index = index[beg_slice:end_slice]

        return self.reindex(**{axis : new_index})

    def _getIndices(self, before, after, axis='major'):
        index = self._get_axis(axis)

        if before is None:
            beg_slice = 0
        else:
            beg_slice = index.searchsorted(before, side='left')

        if after is None:
            end_slice = len(index)
        else:
            end_slice = index.searchsorted(after, side='right')

        return beg_slice, end_slice

#-------------------------------------------------------------------------------
# LongPanel and friends


class LongPanel(Panel):
    """
    Represents long or "stacked" format panel data

    Parameters
    ----------
    values : ndarray (N x K)
    items : sequence
    index : LongPanelIndex

    Note
    ----
    Constructor should probably not be called directly since it
    requires creating the major and minor axis label vectors for for
    the LongPanelIndex
    """

    def __init__(self, values, items, index, factors=None):
        self.items = items
        self.index = index

        self.values = values

        self.factors = factors or {}

    def __len__(self):
        return len(self.index)

    @classmethod
    def fromRecords(cls, data, major_field, minor_field,
                    factors=None, exclude=None):
        """
        Create LongPanel from DataFrame or record / structured ndarray
        object

        Parameters
        ----------
        data : DataFrame, structured or record array, or dict
        major_field : string
        minor_field : string
            Name of field
        factors : list-like, default None
        exclude : list-like, default None

        Returns
        -------
        LongPanel
        """
        if isinstance(data, np.ndarray):
            # Dtype when you have data
            if not issubclass(data.dtype.type, np.void):
                raise Exception('Input was not a structured array!')

            columns = data.dtype.names
            data = dict((k, data[k]) for k in columns)
        elif isinstance(data, DataFrame):
            data = data._series.copy()
        elif isinstance(data, dict):
            # otherwise will pop columns out of original
            data = data.copy()

        if exclude is None:
            exclude = set()
        else:
            exclude = set(exclude)

        major_vec = data.pop(major_field)
        minor_vec = data.pop(minor_field)

        major_axis = Index(sorted(set(major_vec)))
        minor_axis = Index(sorted(set(minor_vec)))

        major_labels, _ = tseries.getMergeVec(major_vec, major_axis.indexMap)
        minor_labels, _ = tseries.getMergeVec(minor_vec, minor_axis.indexMap)

        for col in exclude:
            del data[col]

        factor_dict = {}
        for col in data.keys():
            series = data[col]

            # Is it a factor?
            if not np.issctype(series.dtype):
                factor_dict[col] = factor = Factor.fromarray(series)
                data[col] = factor.labels

        items = sorted(data)
        values = np.array([data[k] for k in items]).T

        index = LongPanelIndex(major_axis, minor_axis,
                               major_labels, minor_labels)

        return LongPanel(values, items, index, factors=factor_dict)

    def toRecords(self):
        major = np.asarray(self.major_axis).take(self.index.major_labels)
        minor = np.asarray(self.minor_axis).take(self.index.minor_labels)

        arrays = [major, minor] + list(self.values[:, i]
                                       for i in range(len(self.items)))

        names = ['major', 'minor'] + list(self.items)

        return np.rec.fromarrays(arrays, names=names)

    @property
    def columns(self):
        """
        So LongPanel can be DataMatrix-like at times
        """
        return self.items

    def cols(self):
        "DataMatrix compatibility"
        return self.columns

    def copy(self):
        """
        Return copy of LongPanel (copies ndarray)

        Returns
        -------
        y : LongPanel
        """
        return LongPanel(self.values.copy(), self.items, self.index,
                         factors=self.factors)

    @property
    def major_axis(self):
        return self.index.major_axis

    @property
    def minor_axis(self):
        return self.index.minor_axis

    def _get_values(self):
        return self._values

    def _set_values(self, values):
        if not values.flags.contiguous:
            values = values.copy()

        shape = len(self.index.major_labels), len(self.items)

        if values.shape != shape:
            raise Exception('Values shape %s mismatch to %s' % (values.shape,
                                                                shape))

        self._values = values

    values = property(fget=_get_values, fset=_set_values)

    def __getitem__(self, key):
        "Return column of panel as LongPanel"

        loc = self.items.indexMap[key]

        return LongPanel(self.values[:, loc : loc + 1].copy(),
                        [key], self.index, factors=self.factors)

    def __setitem__(self, key, value):
        if np.isscalar(value):
            mat = np.empty((len(self.values), 1), dtype=float)
            mat.fill(value)
        elif isinstance(value, np.ndarray):
            mat = value
#             if value.ndim == 1:
#                 value = value.reshape((len(value), 1))
        elif isinstance(value, LongPanel):
            if len(value.items) > 1:
                raise Exception('input LongPanel must only have one column')

            if value.index is not self.index:
                raise Exception('Only can set identically-indexed LongPanel '
                                'items for now')

            mat = value.values

        # Insert item at end of items for now
        self.items = Index(list(self.items) + [key])
        self.values = np.column_stack((self.values, mat))

    def __getstate__(self):
        "Returned pickled representation of the panel"

        return (common._pickle_array(self.values),
                common._pickle_array(self.items),
                self.index)

    def __setstate__(self, state):
        "Unpickle the panel"
        (vals, items, index) = state

        self.items = common._unpickle_array(items)
        self.index = index
        self.values = common._unpickle_array(vals)

    def _combine(self, other, func, axis='items'):
        if isinstance(other, DataFrame):
            return self._combineFrame(other, func, axis=axis)
        elif isinstance(other, Panel):
            return self._combinePanel(other, func)
        elif np.isscalar(other):
            return LongPanel(func(self.values, other), self.items,
                             self.index, factors=self.factors)

    def _combineFrame(self, other, func, axis='items'):
        """
        Arithmetic op

        Parameters
        ----------
        other : DataFrame
        func : function
        axis : int / string

        Returns
        -------
        y : LongPanel
        """
        wide = self.toWide()
        result = wide._combineFrame(other, func, axis=axis)
        return result.toLong()

    def _combinePanel(self, other, func):
        """
        Arithmetic operation between panels
        """
        if self.index is not other.index:
            raise Exception("Can only combine identically-indexed "
                            "panels for now")

        if len(other.items) == 1:
            new_values = func(self.values, other.values)
        else:
            new_values = func(self.values, other.values)

        return LongPanel(new_values, self.items, self.index,
                         factors=self.factors)

    add = _long_arith_method(operator.add, 'add')
    subtract = _long_arith_method(operator.sub, 'subtract')
    divide = _long_arith_method(operator.div, 'divide')
    multiply = _long_arith_method(operator.mul, 'multiply')

    def sort(self, axis='major'):
        """
        Sort value by chosen axis (break ties using other axis)

        Note
        ----
        A LongPanel must be sorted to convert to a WidePanel

        Returns
        -------
        LongPanel (in sorted order)
        """
        if axis == 'major':
            first = self.index.major_labels
            second = self.index.minor_labels

        elif axis == 'minor':
            first = self.index.minor_labels
            second = self.index.major_labels

        # Lexsort starts from END
        indexer = np.lexsort((second, first))

        new_major = self.index.major_labels[indexer]
        new_minor = self.index.minor_labels[indexer]
        new_values = self.values[indexer]

        new_index = LongPanelIndex(self.major_axis, self.minor_axis,
                                   new_major, new_minor)

        new_factors = dict((k, v[indexer])
                           for k, v in self.factors.iteritems())

        return LongPanel(new_values, self.items, new_index,
                         factors=new_factors)

    def toWide(self):
        """
        Transform long (stacked) format into wide format

        Returns
        -------
        WidePanel
        """
        if not self.index.consistent:
            raise PanelError('Panel has duplicate (major, minor) pairs, '
                             'cannot be reliably converted to wide format.')

        I, N, K = self.dims

        values = np.empty((I, N, K), dtype=self.values.dtype)

        mask = self.index.mask
        notmask = -mask

        for i in xrange(len(self.items)):
            values[i].flat[mask] = self.values[:, i]
            values[i].flat[notmask] = np.NaN

        return WidePanel(values, self.items, self.major_axis, self.minor_axis)

    def toCSV(self, path):
        def format_cols(items):
            cols = ['Major', 'Minor'] + list(items)
            return '"%s"' % '","'.join(cols)

        def format_row(major, minor, values):
            vals = ','.join('%.12f' % val for val in values)
            return '%s,%s,%s' % (major, minor, vals)

        f = open(path, 'w')
        self._textConvert(f, format_cols, format_row)
        f.close()

    def toString(self, buffer=sys.stdout, col_space=15):
        """
        Output a screen-friendly version of this Panel
        """
        _pf = common._pfixed
        major_space = max(max([len(str(idx))
                               for idx in self.major_axis]) + 4, 9)
        minor_space = max(max([len(str(idx))
                               for idx in self.minor_axis]) + 4, 9)

        def format_cols(items):
            return '%s%s%s' % (_pf('Major', major_space),
                               _pf('Minor', minor_space),
                               ''.join(_pf(h, col_space) for h in items))

        def format_row(major, minor, values):
            return '%s%s%s' % (_pf(major, major_space),
                               _pf(minor, minor_space),
                               ''.join(_pf(v, col_space) for v in values))

        self._textConvert(buffer, format_cols, format_row)

    def _textConvert(self, buffer, format_cols, format_row):
        print >> buffer, format_cols(self.items)

        label_pairs = zip(self.index.major_labels,
                          self.index.minor_labels)
        major, minor = self.major_axis, self.minor_axis
        for i, (major_i, minor_i) in enumerate(label_pairs):
            row = format_row(major[major_i], minor[minor_i], self.values[i])
            print >> buffer, row

    def _fill_factors(self):
        values = self.values.astype(object)

    def swapaxes(self):
        """
        Swap major and minor axes and reorder values to be grouped by
        minor axis values

        Returns
        -------
        LongPanel (new object)
        """
        # Order everything by minor labels. Have to use mergesort
        # because NumPy quicksort is not stable. Here of course I'm
        # using the property that the major labels are ordered.
        indexer = self.index.minor_labels.argsort(kind='mergesort')

        new_major = self.index.minor_labels.take(indexer)
        new_minor = self.index.major_labels.take(indexer)

        new_values = self.values.take(indexer, axis=0)

        new_index = LongPanelIndex(self.minor_axis,
                                   self.major_axis,
                                   new_major,
                                   new_minor,
                                   mask=self.index.mask)

        return LongPanel(new_values, self.items, new_index)

    def truncate(self, before=None, after=None):
        """
        Slice panel between two major axis values, return complete LongPanel

        Parameters
        ----------
        before : type of major_axis values or None, default None
            None defaults to start of panel

        after : type of major_axis values or None, default None
            None defaults to end of panel

        Returns
        -------
        LongPanel
        """
        left, right = self.index.get_major_bounds(before, after)
        new_index = self.index.truncate(before, after)

        return LongPanel(self.values[left : right],
                         self.items, new_index)

    def filter(self, items):
        """
        Restrict items in panel to input list

        Parameters
        ----------
        items : sequence

        Returns
        -------
        WidePanel
        """
        intersection = self.items.intersection(items)
        indexer = [self.items.indexMap[col] for col in intersection]

        new_values = self.values.take(indexer, axis=1)
        return LongPanel(new_values, intersection, self.index)

    def get_axis_dummies(self, axis='minor', transform=None,
                         prefix=None):
        """
        Construct 1-0 dummy variables corresponding to designated axis
        labels

        Parameters
        ----------
        axis : {'major', 'minor'}, default 'minor'
        transform : function, default None

            Function to apply to axis labels first. For example, to
            get "day of week" dummies in a time series regression you might
            call:

                panel.get_axis_dummies(axis='major',
                                       transform=lambda d: d.weekday())
        Returns
        -------
        LongPanel, item names taken from chosen axis
        """
        if axis == 'minor':
            dim = len(self.minor_axis)
            items = self.minor_axis
            labels = self.index.minor_labels
        elif axis == 'major':
            dim = len(self.major_axis)
            items = self.major_axis
            labels = self.index.major_labels
        else:
            raise Exception('Do not recognize axis %s' % axis)

        if transform:
            mapped = np.array([transform(val) for val in items])

            items = np.array(sorted(set(mapped)))
            labels = items.searchsorted(mapped[labels])
            dim = len(items)

        values = np.eye(dim, dtype=float)
        values = values.take(labels, axis=0)

        result = LongPanel(values, items, self.index)

        if prefix is None:
            prefix = ''

        result = result.addPrefix(prefix)

        return result

    def get_dummies(self, item):
        """
        Use unique values in column of panel to construct LongPanel
        containing dummy

        Parameters
        ----------
        item : object
            Value in panel items Index

        Returns
        -------
        LongPanel
        """
        idx = self.items.indexMap[item]
        values = self.values[:, idx]

        distinct_values = np.array(sorted(set(values)))
        mapping = distinct_values.searchsorted(values)

        values = np.eye(len(distinct_values))

        dummy_mat = values.take(mapping, axis=0)

        return LongPanel(dummy_mat, distinct_values, self.index)

    def mean(self, axis='major', broadcast=False):
        return self.apply(lambda x: np.mean(x, axis=0), axis, broadcast)

    def sum(self, axis='major', broadcast=False):
        return self.apply(lambda x: np.sum(x, axis=0), axis, broadcast)

    def apply(self, f, axis='major', broadcast=False):
        """
        Aggregate over a particular axis

        Parameters
        ----------
        f : function
            NumPy function to apply to each group
        axis : {'major', 'minor'}

        broadcast : boolean

        Returns
        -------
        broadcast=True  -> LongPanel
        broadcast=False -> DataMatrix
        """
        try:
            return self._apply_axis(f, axis=axis, broadcast=broadcast)
        except Exception:
            # ufunc
            new_values = f(self.values)
            return LongPanel(new_values, self.items, self.index)

    def _apply_axis(self, f, axis='major', broadcast=False):
        if axis == 'major':
            panel = self.swapaxes()
            result = panel._apply_axis(f, axis='minor', broadcast=broadcast)
            if broadcast:
                result = result.swapaxes()

            return result

        bounds = self.index._bounds
        values = self.values
        N, _ = values.shape
        result = group_agg(values, bounds, f)

        if broadcast:
            repeater = np.concatenate((np.diff(bounds), [N - bounds[-1]]))
            panel = LongPanel(result.repeat(repeater, axis=0),
                              self.items, self.index)
        else:
            panel = DataMatrix(result, index=self.major_axis,
                               columns=self.items)

        return panel

    def count(self, axis=0):
        if axis == 0:
            lp = self
        else:
            lp = self.swapaxes()

        N = len(lp.values)
        bounds = lp.index._bounds

        return np.concatenate((np.diff(bounds), [N - bounds[-1]]))

    def leftJoin(self, other):
        """

        Parameters
        ----------
        other : LongPanel
        """
        assert(self.index is other.index)

        values = np.concatenate((self.values, other.values), axis=1).copy()
        items = self.items.tolist() + other.items.tolist()

        return LongPanel(values, items, self.index)

    def addPrefix(self, prefix):
        """
        Concatenate prefix string with panel items names.

        Parameters
        ----------
        prefix : string

        Returns
        -------
        LongPanel

        Note
        ----
        does *not* copy values matrix
        """
        new_items = [_prefix_item(item, prefix) for item in self.items]

        return LongPanel(self.values, new_items, self.index)


class LongPanelIndex(object):
    """
    Parameters
    ----------

    """
    def __init__(self, major_axis, minor_axis, major_labels,
                 minor_labels, mask=None):

        self.major_axis = major_axis
        self.minor_axis = minor_axis

        assert(len(minor_labels) == len(major_labels))

        self.major_labels = major_labels
        self.minor_labels = minor_labels

        self._mask = mask

    def __len__(self):
        return len(self.major_labels)

    def __getstate__(self):
        _pickle = common._pickle_array
        return (_pickle(self.major_axis),
                _pickle(self.minor_axis),
                _pickle(self.major_labels),
                _pickle(self.minor_labels))

    def __setstate__(self, state):
        _unpickle = common._unpickle_array

        major, minor, major_labels, minor_labels = state

        self.major_axis = _unpickle(major)
        self.minor_axis = _unpickle(minor)

        self.major_labels = _unpickle(major_labels)
        self.minor_labels = _unpickle(minor_labels)

    @property
    def consistent(self):
        offset = max(len(self.major_axis), len(self.minor_axis))

        # overflow risk
        if (offset + 1) ** 2 > 2**32:
            keys = (self.major_labels.astype(np.int64) * offset +
                    self.minor_labels.astype(np.int64))
        else:
            keys = self.major_labels * offset + self.minor_labels

        unique_keys = np.unique(keys)

        if len(unique_keys) < len(keys):
            return False

        return True

    def truncate(self, before=None, after=None):
        """
        Slice index between two major axis values, return new
        LongPanelIndex

        Parameters
        ----------
        before : type of major_axis values or None, default None
            None defaults to start of panel

        after : type of major_axis values or None, default None
            None defaults to after of panel

        Returns
        -------
        LongPanelIndex
        """
        i, j = self._get_axis_bounds(before, after)
        left, right = self._get_label_bounds(i, j)

        return LongPanelIndex(self.major_axis[i : j],
                              self.minor_axis,
                              self.major_labels[left : right] - i,
                              self.minor_labels[left : right])

    def get_major_bounds(self, begin=None, end=None):
        """
        Return index bounds for slicing LongPanel labels and / or
        values

        Parameters
        ----------
        begin : axis value or None
        end : axis value or None

        Returns
        -------
        y : tuple
            (left, right) absolute bounds on LongPanel values
        """
        i, j = self._get_axis_bounds(begin, end)
        left, right = self._get_label_bounds(i, j)

        return left, right

    def _get_axis_bounds(self, begin, end):
        """
        Return major axis locations corresponding to interval values
        """
        if begin is not None:
            i = self.major_axis.indexMap.get(begin)
            if i is None:
                i = self.major_axis.searchsorted(begin, side='right')
        else:
            i = 0

        if end is not None:
            j = self.major_axis.indexMap.get(end)
            if j is None:
                j = self.major_axis.searchsorted(end)
            else:
                j = j + 1
        else:
            j = len(self.major_axis)

        if i > j:
            raise Exception('Must have begin <= end!')

        return i, j

    def _get_label_bounds(self, i, j):
        "Return slice points between two major axis locations"

        left = self._bounds[i]

        if j >= len(self.major_axis):
            right = len(self.major_labels)
        else:
            right = self._bounds[j]

        return left, right

    __bounds = None
    @property
    def _bounds(self):
        "Return or compute and return slice points for major axis"
        if self.__bounds is None:
            inds = np.arange(len(self.major_axis))
            self.__bounds = self.major_labels.searchsorted(inds)

        return self.__bounds

    @property
    def mask(self):
        if self._mask is None:
            self._mask = self._makeMask()

        return self._mask

    def _makeMask(self):
        """
        Create observation selection vector using major and minor
        labels, for converting to wide format.
        """
        N, K = self.dims
        selector = self.minor_labels + K * self.major_labels

        mask = np.zeros(N * K, dtype=bool)
        mask[selector] = True

        return mask

    @property
    def dims(self):
        return len(self.major_axis), len(self.minor_axis)


class Factor(object):
    """
    Represents a categorical variable in classic R / S+ fashion
    """
    def __init__(self, labels, levels):
        self.labels = labels
        self.levels = levels

    @classmethod
    def fromarray(cls, values):
        levels = np.array(sorted(set(values)), dtype=object)
        labels = levels.searchsorted(values)

        return Factor(labels, levels=levels)

    def __repr__(self):
        temp = 'Factor:\n%s\nLevels (%d): %s'

        values = self.levels[self.labels]
        return temp % (repr(values), len(self.levels), self.levels)

    def __getitem__(self, key):
        if key is None and key not in self.index:
            raise Exception('None/Null object requested of Series!')

        if isinstance(key, int):
            i = self.labels[key]
            return self.levels[i]
        else:
            new_labels = self.labels[key]
            return Factor(new_labels, self.levels)

def factor_agg(factor, vec, func):
    """
    Parameters
    ----------
    factor : Factor
        length n
    vec : sequence
        length n
    func : function
        1D array aggregation function

    Returns
    -------
    ndarray corresponding to Factor levels
    """
    indexer = np.argsort(factor.labels)
    unique_labels = np.arange(len(factor.levels))

    ordered_labels = factor.labels.take(indexer)
    ordered_vec = np.asarray(vec).take(indexer)
    bounds = ordered_labels.searchsorted(unique_labels)

    return group_agg(ordered_vec, bounds, func)

def group_agg(values, bounds, f):
    """
    R-style aggregator

    Parameters
    ----------
    values : N-length or N x K ndarray
    bounds : B-length ndarray
    f : ndarray aggregation function

    Returns
    -------
    ndarray with same length as bounds array
    """
    if values.ndim == 1:
        N = len(values)
        result = np.empty(len(bounds), dtype=float)
    elif values.ndim == 2:
        N, K = values.shape
        result = np.empty((len(bounds), K), dtype=float)

    testagg = f(values[:min(1, len(values))])
    if isinstance(testagg, np.ndarray) and testagg.ndim == 2:
        raise Exception('Passed function does not aggregate!')

    for i, left_bound in enumerate(bounds):
        if i == len(bounds) - 1:
            right_bound = N
        else:
            right_bound = bounds[i + 1]

        result[i] = f(values[left_bound : right_bound])

    return result

def _prefix_item(item, prefix=None):
    if prefix is None:
        return item

    if isinstance(item, float):
        template = '%g%s'
    else:
        template = '%s%s'

    return template % (prefix, item)

def _homogenize(frames, intersect=True):
    """
    Conform set of DataFrame-like objects to either an intersection
    of indices / columns or a union.

    Parameters
    ----------
    frames : dict
    intersect : boolean, default True

    Returns
    -------
    dict of aligned frames, index, columns
    """
    result = {}

    index = None
    columns = None

    adj_frames = {}
    for k, v in frames.iteritems():
        if isinstance(v, dict):
            adj_frames[k] = DataMatrix(v)
        else:
            adj_frames[k] = v

    if intersect:
        for key, frame in adj_frames.iteritems():
            if index is None:
                index = frame.index
            elif index is not frame.index:
                index = index.intersection(frame.index)

            if columns is None:
                columns = set(frame.cols())
            else:
                columns &= set(frame.cols())
    else:
        for key, frame in adj_frames.iteritems():
            if index is None:
                index = frame.index
            elif index is not frame.index:
                index = index.union(frame.index)

            if columns is None:
                columns = set(frame.cols())
            else:
                columns |= set(frame.cols())

    columns = sorted(columns)

    if intersect:
        for key, frame in adj_frames.iteritems():
            result[key] = frame.filter(columns).reindex(index)
    else:
        for key, frame in adj_frames.iteritems():
            if not isinstance(frame, DataMatrix):
                frame = frame.toDataMatrix()

            result[key] = frame.reindex(index=index, columns=columns)

    return result, index, columns

def pivot(index, columns, values):
    """
    Produce 'pivot' table based on 3 columns of this DataFrame.
    Uses unique values from index / columns and fills with values.

    Parameters
    ----------
    index : ndarray
        Labels to use to make new frame's index
    columns : ndarray
        Labels to use to make new frame's columns
    values : ndarray
        Values to use for populating new frame's values

    Note
    ----
    Obviously, all 3 of the input arguments must have the same length

    Returns
    -------
    DataMatrix
    """
    if not (len(index) == len(columns) == len(values)):
        raise Exception('Pivot inputs must all be same length!')

    if len(index) == 0:
        return DataMatrix(index=[])

    major_axis = Index(sorted(set(index)))
    minor_axis = Index(sorted(set(columns)))

    major_labels, _ = tseries.getMergeVec(index, major_axis.indexMap)
    minor_labels, _ = tseries.getMergeVec(columns, minor_axis.indexMap)

    valueMat = values.view(np.ndarray).reshape(len(values), 1)

    longIndex = LongPanelIndex(major_axis, minor_axis,
                               major_labels, minor_labels)

    longPanel = LongPanel(valueMat, ['foo'], longIndex)
    longPanel = longPanel.sort()

    try:
        return longPanel.toWide()['foo']
    except PanelError:
        return _slow_pivot(index, columns, values)

def _slow_pivot(index, columns, values):
    """
    Produce 'pivot' table based on 3 columns of this DataFrame.
    Uses unique values from index / columns and fills with values.

    Parameters
    ----------
    index : string or object
        Column name to use to make new frame's index
    columns : string or object
        Column name to use to make new frame's columns
    values : string or object
        Column name to use for populating new frame's values

    Could benefit from some Cython here.
    """
    from itertools import izip
    tree = {}
    for i, (idx, col) in enumerate(izip(index, columns)):
        if col not in tree:
            tree[col] = {}
        branch = tree[col]
        branch[idx] = values[i]

    return DataFrame(tree)

def _monotonic(arr):
    return not (arr[1:] < arr[:-1]).any()

#-------------------------------------------------------------------------------
# GroupBy

class WidePanelGroupBy(GroupBy):

    def __init__(self, obj, grouper, axis=0):
        self.axis = axis

        if axis not in (0, 1, 2): # pragma: no cover
            raise Exception('invalid axis')

        GroupBy.__init__(self, obj, grouper)

    @property
    def _group_axis(self):
        return self.obj._get_axis(self.axis)

    def aggregate(self, applyfunc):
        """
        For given DataFrame, group index by given mapper function or dict, take
        the sub-DataFrame (reindex) for this group and call apply(applyfunc)
        on this sub-DataFrame. Return a DataFrame of the results for each
        key.

        Parameters
        ----------
        mapper : function, dict-like, or string
            Mapping or mapping function. If string given, must be a column
            name in the frame
        applyfunc : function
            Function to use for aggregating groups

        N.B.: applyfunc must produce one value from a Series, otherwise
        an error will occur.

        Optional: provide set mapping as dictionary
        """
        axis_name = self.obj._get_axis_name(self.axis)
        getter = lambda p, group: p.reindex(**{axis_name : group})
        result_d = self._aggregate_generic(getter, applyfunc,
                                           axis=self.axis)

        result = WidePanel.fromDict(result_d, intersect=False)

        if self.axis > 0:
            result = result.swapaxes(0, self.axis)

        return result

class LongPanelGroupBy(GroupBy):
    pass
