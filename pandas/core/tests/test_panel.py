import os
import operator
import unittest

from numpy.random import randint
import numpy as np

from pandas.core.api import Index, notnull
from pandas.core.datetools import bday
from pandas.core.panel import WidePanel, LongPanelIndex, LongPanel
from pandas.core.tests.common import (assert_frame_equal,
                                      assert_series_equal,
                                      assert_almost_equal)
import pandas.core.tests.common as common

class PanelTests(object):

    def test_iter(self):
        common.equalContents(list(self.panel), self.panel.items)

    def test_pickle(self):
        import cPickle

        pickled = cPickle.dumps(self.panel)
        unpickled = cPickle.loads(pickled)

        assert_frame_equal(unpickled['ItemA'], self.panel['ItemA'])

    def test_repr(self):
        foo = repr(self.panel)

    def test_set_values(self):
        self.panel.values = np.array(self.panel.values, order='F')

        assert(self.panel.values.flags.contiguous)

    def _check_statistic(self, frame, name, alternative):
        f = getattr(frame, name)

        for i, ax in enumerate(['items', 'major', 'minor']):
            result = f(axis=i)
            assert_frame_equal(result, frame.apply(alternative, axis=ax))

    def test_count(self):
        f = lambda s: notnull(s).sum()

        self._check_statistic(self.panel, 'count', f)

    def test_sum(self):
        def f(x):
            x = np.asarray(x)
            nona = x[notnull(x)]

            if len(nona) == 0:
                return np.NaN
            else:
                return nona.sum()

        self._check_statistic(self.panel, 'sum', f)

    def test_prod(self):
        def f(x):
            x = np.asarray(x)
            nona = x[notnull(x)]

            if len(nona) == 0:
                return np.NaN
            else:
                return np.prod(nona)

        self._check_statistic(self.panel, 'prod', f)

    def test_mean(self):
        def f(x):
            x = np.asarray(x)
            return x[notnull(x)].mean()

        self._check_statistic(self.panel, 'mean', f)

    def test_median(self):
        def f(x):
            x = np.asarray(x)
            return np.median(x[notnull(x)])

        self._check_statistic(self.panel, 'median', f)

    def test_min(self):
        def f(x):
            x = np.asarray(x)
            nona = x[notnull(x)]

            if len(nona) == 0:
                return np.NaN
            else:
                return nona.min()

        self._check_statistic(self.panel, 'min', f)

    def test_max(self):
        def f(x):
            x = np.asarray(x)
            nona = x[notnull(x)]

            if len(nona) == 0:
                return np.NaN
            else:
                return nona.max()

        self._check_statistic(self.panel, 'max', f)

    def test_var(self):
        def f(x):
            x = np.asarray(x)
            nona = x[notnull(x)]

            if len(nona) < 2:
                return np.NaN
            else:
                return nona.var(ddof=1)

        self._check_statistic(self.panel, 'var', f)

    def test_std(self):
        def f(x):
            x = np.asarray(x)
            nona = x[notnull(x)]

            if len(nona) < 2:
                return np.NaN
            else:
                return nona.std(ddof=1)

        self._check_statistic(self.panel, 'std', f)

    def test_skew(self):
        return
        try:
            from scipy.stats import skew
        except ImportError:
            return

        def f(x):
            x = np.asarray(x)
            return skew(x[notnull(x)], bias=False)

        self._check_statistic(self.panel, 'skew', f)

    def test_cumsum(self):
        cumsum = self.panel.cumsum()

        assert_frame_equal(cumsum['ItemA'], self.panel['ItemA'].cumsum())

class TestWidePanel(unittest.TestCase, PanelTests):

    def setUp(self):
        self.panel = common.makeWidePanel()

        common.add_nans(self.panel)

    def test_get_axis(self):
        assert(self.panel._get_axis(0) is self.panel.items)
        assert(self.panel._get_axis(1) is self.panel.major_axis)
        assert(self.panel._get_axis(2) is self.panel.minor_axis)

    def test_get_axis_number(self):
        assert(self.panel._get_axis_number('items'), 0)
        assert(self.panel._get_axis_number('major'), 1)
        assert(self.panel._get_axis_number('minor'), 2)

    def test_get_axis_name(self):
        assert(self.panel._get_axis_name(0), 'items')
        assert(self.panel._get_axis_name(1), 'major')
        assert(self.panel._get_axis_name(2), 'minor')

    def test_get_plane_axes(self):
        # what to do here?

        index, columns = self.panel._get_plane_axes('items')
        index, columns = self.panel._get_plane_axes('major')
        index, columns = self.panel._get_plane_axes('minor')

        index, columns = self.panel._get_plane_axes(0)

    def test_arith(self):
        def test_op(panel, op):
            result = op(panel, 1)
            assert_frame_equal(result['ItemA'], op(panel['ItemA'], 1))

        test_op(self.panel, operator.add)
        test_op(self.panel, operator.sub)
        test_op(self.panel, operator.mul)
        test_op(self.panel, operator.div)
        test_op(self.panel, operator.pow)

        test_op(self.panel, lambda x, y: y + x)
        test_op(self.panel, lambda x, y: y - x)
        test_op(self.panel, lambda x, y: y * x)
        test_op(self.panel, lambda x, y: y / x)
        test_op(self.panel, lambda x, y: y ** x)

        self.assertRaises(Exception, self.panel.__add__, self.panel['ItemA'])

    def test_fromDict(self):
        pass

    def test_keys(self):
        common.equalContents(self.panel.keys(), self.panel.items)

    def test_iteritems(self):
        # just test that it works
        for k, v in self.panel.iteritems():
            pass

        self.assertEqual(len(list(self.panel.iteritems())),
                         len(self.panel.items))

    def test_values(self):
        pass

    def test_getitem(self):
        pass

    def test_delitem_pop(self):
        expected = self.panel['ItemA']
        result = self.panel.pop('ItemA')
        assert_frame_equal(expected, result)
        self.assert_('ItemA' not in self.panel.items)

    def test_setitem(self):

        # LongPanel with one item
        lp = self.panel.filterItems(['ItemA']).toLong()
        self.panel['ItemE'] = lp

        lp = self.panel.filterItems(['ItemA', 'ItemB']).toLong()
        self.assertRaises(Exception, self.panel.__setitem__,
                          'ItemE', lp)

        # DataFrame
        df = self.panel['ItemA'][2:].filter(items=['A', 'B'])
        self.panel['ItemF'] = df
        self.panel['ItemE'] = df

        df2 = self.panel['ItemF']

        assert_frame_equal(df, df2.reindex(index=df.index,
                                           columns=df.columns))

        # scalar
        self.panel['ItemG'] = 1
        self.panel['ItemE'] = 1

    def test_conform(self):
        df = self.panel['ItemA'][:-5].filter(items=['A', 'B'])
        conformed = self.panel.conform(df)

        assert(conformed.index.equals(self.panel.major_axis))
        assert(conformed.columns.equals(self.panel.minor_axis))

    def test_reindex(self):
        ref = self.panel['ItemB']

        # items
        result = self.panel.reindex(items=['ItemA', 'ItemB'])
        assert_frame_equal(result['ItemB'], ref)

        # major
        new_major = self.panel.major_axis[:10]
        result = self.panel.reindex(major=new_major)
        assert_frame_equal(result['ItemB'], ref.reindex(index=new_major))

        # minor
        new_minor = self.panel.minor_axis[:2]
        result = self.panel.reindex(minor=new_minor)
        assert_frame_equal(result['ItemB'], ref.reindex(columns=new_minor))

        result = self.panel.reindex(items=self.panel.items,
                                    major=self.panel.major_axis,
                                    minor=self.panel.minor_axis)

        assert(result.items is self.panel.items)
        assert(result.major_axis is self.panel.major_axis)
        assert(result.minor_axis is self.panel.minor_axis)

        self.assertRaises(Exception, self.panel.reindex)

        # with filling
        smaller_major = self.panel.major_axis[::5]
        smaller = self.panel.reindex(major=smaller_major)

        larger = smaller.reindex(major=self.panel.major_axis,
                                 fill_method='pad')

        assert_frame_equal(larger.getMajorXS(self.panel.major_axis[1]),
                           smaller.getMajorXS(smaller_major[0]))

    def test_combineFrame(self):
        def check_op(op, name):
            # items
            df = self.panel['ItemA']

            func = getattr(self.panel, name)

            result = func(df, axis='items')

            assert_frame_equal(result['ItemB'], op(self.panel['ItemB'], df))

            # major
            xs = self.panel.getMajorXS(self.panel.major_axis[0])
            result = func(xs, axis='major')

            idx = self.panel.major_axis[1]

            assert_frame_equal(result.getMajorXS(idx),
                               op(self.panel.getMajorXS(idx), xs))

            # minor
            xs = self.panel.getMinorXS(self.panel.minor_axis[0])
            result = func(xs, axis='minor')

            idx = self.panel.minor_axis[1]

            assert_frame_equal(result.getMinorXS(idx),
                               op(self.panel.getMinorXS(idx), xs))

        check_op(operator.add, 'add')
        check_op(operator.sub, 'subtract')
        check_op(operator.mul, 'multiply')
        check_op(operator.div, 'divide')

    def test_combinePanel(self):
        pass

    def test_operators(self):
        pass

    def test_getMajorXS(self):
        ref = self.panel['ItemA']

        idx = self.panel.major_axis[5]
        xs = self.panel.getMajorXS(idx)

        assert_series_equal(xs['ItemA'], ref.getXS(idx))

        # not contained
        idx = self.panel.major_axis[0] - bday
        self.assertRaises(Exception, self.panel.getMajorXS, idx)

    def test_getMinorXS(self):
        ref = self.panel['ItemA']

        idx = self.panel.minor_axis[1]
        xs = self.panel.getMinorXS(idx)

        assert_series_equal(xs['ItemA'], ref[idx])

        # not contained
        self.assertRaises(Exception, self.panel.getMinorXS, 'E')

    def test_groupby(self):
        pass

    def test_swapaxes(self):
        result = self.panel.swapaxes('items', 'minor')
        self.assert_(result.items is self.panel.minor_axis)

        result = self.panel.swapaxes('items', 'major')
        self.assert_(result.items is self.panel.major_axis)

        result = self.panel.swapaxes('major', 'minor')
        self.assert_(result.major_axis is self.panel.minor_axis)

        # this should also work
        result = self.panel.swapaxes(0, 1)
        self.assert_(result.items is self.panel.major_axis)

    def test_toLong(self):
        # filtered
        filtered = self.panel.toLong()

        # unfiltered
        unfiltered = self.panel.toLong(filter_observations=False)


    def test_filterItems(self):
        pass

    def test_apply(self):
        pass

    def test_shift(self):
        # major
        idx = self.panel.major_axis[0]
        idx_lag = self.panel.major_axis[1]

        shifted = self.panel.shift(1)

        assert_frame_equal(self.panel.getMajorXS(idx),
                           shifted.getMajorXS(idx_lag))

        # minor
        idx = self.panel.minor_axis[0]
        idx_lag = self.panel.minor_axis[1]

        shifted = self.panel.shift(1, axis='minor')

        assert_frame_equal(self.panel.getMinorXS(idx),
                           shifted.getMinorXS(idx_lag))

        self.assertRaises(Exception, self.panel.shift, axis='items')

class TestLongPanelIndex(unittest.TestCase):

    def setUp(self):
        major_axis = Index([1, 2, 3, 4])
        minor_axis = Index([1, 2])

        major_labels = np.array([0, 0, 1, 2, 3, 3])
        minor_labels = np.array([0, 1, 0, 1, 0, 1])

        self.index = LongPanelIndex(major_axis, minor_axis,
                                    major_labels, minor_labels)

        major_labels = np.array([0, 0, 1, 1, 1, 2, 2, 3, 3])
        minor_labels = np.array([0, 1, 0, 1, 1, 0, 1, 0, 1])

        self.incon = LongPanelIndex(major_axis, minor_axis,
                                    major_labels, minor_labels)

    def test_isConsistent(self):
        self.assert_(self.index.isConsistent())
        self.assert_(not self.incon.isConsistent())

        # need to construct an overflow
        major_axis = range(70000)
        minor_axis = range(10)

        major_labels = np.arange(70000)
        minor_labels = np.repeat(range(10), 7000)

        index = LongPanelIndex(major_axis, minor_axis,
                               major_labels, minor_labels)

        self.assert_(index.isConsistent())

    def test_truncate(self):
        result = self.index.truncate(before=1)
        self.assert_(0 not in result.major_axis)
        self.assert_(1 in result.major_axis)

        result = self.index.truncate(after=1)
        self.assert_(2 not in result.major_axis)
        self.assert_(1 in result.major_axis)

        result = self.index.truncate(before=1, after=2)
        self.assertEqual(len(result.major_axis), 2)

    def test_getMajorBounds(self):
        pass

    def test_getAxisBounds(self):
        pass

    def test_getLabelBounds(self):
        pass

    def test_bounds(self):
        pass

    def test_makeMask(self):
        mask =  self.index.mask
        expected = np.array([True, True,
                             True, False,
                             False, True,
                             True, True], dtype=bool)
        self.assert_(np.array_equal(mask, expected))

    def test_dims(self):
        pass

class TestLongPanel(unittest.TestCase):

    def setUp(self):
        panel = common.makeWidePanel()
        common.add_nans(panel)

        self.panel = panel.toLong()
        self.unfiltered_panel = panel.toLong(filter_observations=False)

    def test_pickle(self):
        import cPickle

        pickled = cPickle.dumps(self.panel)
        unpickled = cPickle.loads(pickled)

        assert_almost_equal(unpickled['ItemA'].values,
                            self.panel['ItemA'].values)

    def test_constructor(self):
        pass

    def test_fromRecords(self):
        pass

    def test_columns(self):
        pass

    def test_copy(self):
        pass

    def test_values(self):
        pass

    def test_getitem(self):
        col = self.panel['ItemA']

    def test_setitem(self):
        self.panel['ItemE'] = self.panel['ItemA']

    def test_pickle(self):
        pass

    def test_combineFrame(self):
        pass

    def test_combinePanel(self):
        pass

    def test_operators(self):
        pass

    def test_sort(self):
        def is_sorted(arr):
            return (arr[1:] > arr[:-1]).any()

        sorted_minor = self.panel.sort(axis='minor')
        self.assert_(is_sorted(sorted_minor.index.minor_labels))

        sorted_major = sorted_minor.sort(axis='major')
        self.assert_(is_sorted(sorted_major.index.major_labels))

    def test_toWide(self):
        pass

    def test_toCSV(self):
        self.panel.toCSV('__tmp__')
        os.remove('__tmp__')

    def test_toString(self):
        from cStringIO import StringIO

        buf = StringIO()
        self.panel.toString(buf)
        self.panel.toString(buf, col_space=12)

    def test_swapaxes(self):
        swapped = self.panel.swapaxes()

        self.assert_(swapped.major_axis is self.panel.minor_axis)

        # what else to test here?

    def test_truncate(self):
        pass

    def test_filterItems(self):
        pass

    def test_getAxisDummies(self):
        pass

    def test_getFrameDummies(self):
        pass

    def test_getItemDummies(self):
        pass

    def test_applyToAxis(self):
        pass

    def test_mean(self):
        pass

    def test_sum(self):
        pass

    def test_apply(self):
        pass

    def test_count(self):
        pass

    def test_leftJoin(self):
        pass

    def test_merge(self):
        pass

    def test_addPrefix(self):
        pass

class TestFactor(unittest.TestCase):

    def test_constructor(self):
        pass

