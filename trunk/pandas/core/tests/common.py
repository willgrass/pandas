from datetime import datetime
import random
import string

from numpy.random import randn
import numpy as np

from pandas.core.api import DateRange, Index, Series, DataFrame

N = 100
K = 10

def rands(n):
    choices = string.letters + string.digits
    return ''.join([random.choice(choices) for _ in xrange(n)])

def equalContents(arr1, arr2):
    """Checks if the set of unique elements of arr1 and arr2 are equivalent.
    """
    return frozenset(arr1) == frozenset(arr2)

def isiterable(obj):
    return hasattr(obj, '__iter__')

def assert_almost_equal(a, b):
    if isiterable(a):
        np.testing.assert_(isiterable(b))
        np.testing.assert_equal(len(a), len(b))
        for i in xrange(len(a)):
            assert_almost_equal(a[i], b[i])
        return

    err_msg = lambda a, b: 'expected %.5f but got %.5f' % (a, b)

    if np.isnan(a):
        np.testing.assert_(np.isnan(b))
        return

    # case for zero
    if abs(a) < 1e-5:
        np.testing.assert_almost_equal(
            a, b, decimal=5, err_msg=err_msg(a, b), verbose=False)
    else:
        np.testing.assert_almost_equal(
            1, a/b, decimal=5, err_msg=err_msg(a, b), verbose=False)

def assert_dict_equal(a, b):
    a_keys = frozenset(a.keys())
    b_keys = frozenset(b.keys())

    assert(a_keys == b_keys)

    for k in a_keys:
        assert_almost_equal(a[k], b[k])

def getCols(k):
    return string.ascii_uppercase[:k]

def makeStringIndex(k):
    return Index([rands(10) for _ in xrange(k)])

def makeIntIndex(k):
    return Index(np.arange(k))

def makeDateIndex(k):
    dates = list(DateRange(datetime(2000, 1, 1), periods=k))
    return Index(dates)

def makeFloatSeries():
    index = makeStringIndex(N)
    return Series(randn(N), index=index)

def makeStringSeries():
    index = makeStringIndex(N)
    return Series(randn(N), index=index)

def makeObjectSeries():
    dateIndex = makeDateIndex(N)
    index = makeStringIndex(N)
    return Series(dateIndex, index=index)

def makeTimeSeries():
    return Series(randn(N), index=makeDateIndex(N))

def getArangeMat():
    return np.arange(N * K).reshape((N, K))

def getSeriesData():
    index = makeStringIndex(N)

    return dict((c, Series(randn(N), index=index)) for c in getCols(K))

def getTimeSeriesData():
    return dict((c, makeTimeSeries()) for c in getCols(K))

def makeDataFrame():
    data = getSeriesData()
    return DataFrame(data)

def makeTimeDataFrame():
    data = getTimeSeriesData()
    return DataFrame(data)

def makeDataMatrix():
    data = getSeriesData()
    return DataFrame(data)

def makeTimeDataMatrix():
    data = getTimeSeriesData()
    return DataFrame(data)
