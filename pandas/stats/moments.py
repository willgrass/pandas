"""
Provides rolling statistical moments and related descriptive
statistics implemented in Cython
"""
from functools import wraps

from numpy import NaN
import numpy as np

from pandas.core.api import (DataFrame, DataMatrix, Series, notnull)
import pandas.lib.tseries as tseries
import pandas.util.misc as misc_util

__all__ = ['rolling_count', 'rolling_max', 'rolling_min',
           'rolling_sum', 'rolling_mean', 'rolling_std', 'rolling_cov',
           'rolling_corr', 'rolling_var', 'rolling_skew', 'rolling_kurt',
           'rolling_median', 'ewma', 'ewmvol', 'ewmcorr', 'ewmcov']


#-------------------------------------------------------------------------------
# Python interface to Cython functions

def _check_arg(arg):
    if not issubclass(arg.dtype.type, float):
        arg = arg.astype(float)

    return arg

def _two_periods(minp, window):
    if minp is None:
        return window
    else:
        return max(2, minp)

def _use_window(minp, window):
    if minp is None:
        return window
    else:
        return minp

def _wrap_cython(f, check_minp=_use_window):
    def wrapper(arg, window, minp=None):
        minp = check_minp(minp, window)
        arg = _check_arg(arg)
        return f(arg, window, minp)

    return wrapper

_rolling_sum = _wrap_cython(tseries.roll_sum)
_rolling_max = _wrap_cython(tseries.roll_max)
_rolling_min = _wrap_cython(tseries.roll_min)
_rolling_mean = _wrap_cython(tseries.roll_mean)
_rolling_median = _wrap_cython(tseries.roll_median)
_rolling_var = _wrap_cython(tseries.roll_var, check_minp=_two_periods)
_rolling_skew = _wrap_cython(tseries.roll_skew, check_minp=_two_periods)
_rolling_kurt = _wrap_cython(tseries.roll_kurt, check_minp=_two_periods)
_rolling_std = lambda *a, **kw: np.sqrt(_rolling_var(*a, **kw))

def _ewma(arg, com):
    arg = _check_arg(arg)
    return tseries.ewma(arg, com)

#-------------------------------------------------------------------------------
# Rolling statistics

_doc_template = """
%s

Parameters
----------
arg : 1D ndarray, Series, or DataFrame/DataMatrix
window : Number of observations used for calculating statistic
min_periods : int
    Minimum number of observations in window required to have a value
time_rule : {None, 'WEEKDAY', 'EOM', 'W@MON', ...}, default=None
    Name of time rule to conform to before computing statistic

Returns
-------
y : type of input argument
"""

def _rolling_func(func, desc):
    @wraps(func)
    def f(arg, window, min_periods=None, time_rule=None):
        return _rollingMoment(arg, window, func, min_periods,
                              time_rule=time_rule)

    f.__doc__ = _doc_template % desc

    return f

def rolling_count(arg, window, time_rule=None):
    """
    Rolling count of number of observations inside provided window.

    Parameters
    ----------
    arg :  DataFrame or numpy ndarray-like
    window : Number of observations used for calculating statistic
    """
    types = (DataFrame, DataMatrix, Series)
    if time_rule is not None and isinstance(arg, types):
        # Conform to whatever frequency needed.
        arg = arg.asfreq(time_rule)

    window = min(window, len(arg))
    if isinstance(arg, DataMatrix):
        arg = arg.copy()
        arg.values = np.isfinite(arg.values).astype(float)
        result = rolling_sum(arg, window, min_periods=1, time_rule=time_rule)
        result.values[np.isnan(result.values)] = 0
    elif isinstance(arg, DataFrame):
        converter = lambda x: np.isfinite(x).astype(float)
        arg = arg.apply(converter)
        result = rolling_sum(arg, window, min_periods=1, time_rule=time_rule)
        result = result.fill(value=0)
    else:
        arg = np.isfinite(arg).astype(float)
        result = rolling_sum(arg, window, min_periods=1, time_rule=time_rule)
        result[np.isnan(result)] = 0
    return result

def rolling_cov(arg1, arg2, window, min_periods=None, time_rule=None):
    """
    Unbiased moving covariance

    Parameters
    ----------
    arg :  DataFrame or numpy ndarray-like
    window : Number of observations used for calculating statistic
    min_periods : int
        Minimum number of observations in window required to have a value
    time_rule : {None, 'WEEKDAY', 'EOM', 'W@MON', ...}, default=None
        Name of time rule to conform to before computing statistic
    """
    num1 = rolling_mean(arg1*arg2, window, min_periods, time_rule) #E(XY)
    num2 = (rolling_mean(arg1, window, min_periods, time_rule) *
            rolling_mean(arg2, window, min_periods, time_rule)) #E(X)E(Y)
    return (num1 - num2) * window / (window - 1)

def rolling_corr(arg1, arg2, window, min_periods=None, time_rule=None):
    """
    Moving correlation

    Parameters
    ----------
    arg :  DataFrame or numpy ndarray-like
    window : Number of observations used for calculating statistic
    min_periods : int
        Minimum number of observations in window required to have a value
    time_rule : {None, 'WEEKDAY', 'EOM', 'W@MON', ...}, default=None
        Name of time rule to conform to before computing statistic
    """
    num = rolling_cov(arg1, arg2, window, min_periods, time_rule)
    den  = (rolling_std(arg1, window, min_periods, time_rule) *
            rolling_std(arg2, window, min_periods, time_rule))
    return num / den

rolling_max = _rolling_func(_rolling_max, 'Moving maximum')
rolling_min = _rolling_func(_rolling_min, 'Moving minimum')
rolling_sum = _rolling_func(_rolling_sum, 'Moving sum')
rolling_mean = _rolling_func(_rolling_mean, 'Moving mean')
rolling_median = _rolling_func(_rolling_median, 'Moving median')
rolling_std = _rolling_func(_rolling_std,
                            'Unbiased moving standard deviation')
rolling_var = _rolling_func(_rolling_var, 'Unbiased moving variance')
rolling_skew = _rolling_func(_rolling_skew, 'Unbiased moving skewness')
rolling_kurt = _rolling_func(_rolling_kurt, 'Unbiased moving kurtosis')

def _rollingMoment(arg, window, func, minp, time_rule=None):
    """
    Rolling statistical measure using supplied function. Designed to be
    used with passed-in Cython array-based functions.

    Parameters
    ----------
    arg :  DataFrame or numpy ndarray-like
    window : Number of observations used for calculating statistic
    func : Cython function to compute rolling statistic on raw series
    minp : int
        Minimum number of observations required to have a value
    """
    types = (DataFrame, DataMatrix, Series)
    if time_rule is not None and isinstance(arg, types):
        # Conform to whatever frequency needed.
        arg = arg.asfreq(time_rule)

    if isinstance(arg, DataMatrix):
        T, N = arg.values.shape
        resultMatrix = np.empty((T, N), dtype=arg.values.dtype)
        arg.values[np.isinf(arg.values)] = NaN
        for i in range(N):
            resultMatrix[:, i] = func(arg.values[:, i], window, minp=minp)
        output = DataMatrix(resultMatrix, index=arg.index,
                            columns=arg.columns)

    elif isinstance(arg, DataFrame):
        output = DataFrame(index = arg.index)
        for col, series in arg.iteritems():
            series[np.isinf(series)] = NaN
            output[col] = Series(func(series, window, minp=minp),
                                 index=series.index)
    elif isinstance(arg, Series):
        arg[np.isinf(arg)] = NaN
        output = Series(func(arg, window, minp=minp), index=arg.index)
    else:
        try:
            assert(hasattr(arg, '__iter__'))
        except AssertionError:
            raise AssertionError('Expected DataFrame or array-like argument')
        arg[np.isinf(arg)] = NaN
        output = func(arg, window, minp=minp)
    return output

#-------------------------------------------------------------------------------
# Exponential moving moments

def _getMinPeriods(minPct, rho):
    if not (0 <= minPct <= 1):
        raise Exception('minPct must be between 0 and 1!')

    if minPct == 0:
        return 0

    return int(np.ceil(np.log(minPct) / np.log(rho)))

def _ewmoment(values, func, min_periods=None, biasCorrection=None):
    """
    Generic rolling exponential moment function using blended accumulator
    method.

    Parameters
    ----------
    values : ndarray or Series
    func : function
        taking previous value and next value

    biasCorrection : float
        Optional bias correction

    min_periods : int, optional
        require a particular number of periods "in window" to compute statistic
        If provided, overrides the minPct argument

    Returns
    -------
    Same type and length as values argument
    """
    okLocs = notnull(values)

    cleanValues = values[okLocs]

    result = np.frompyfunc(func, 2, 1).accumulate(cleanValues)
    result = result.astype(float)

    if min_periods is not None:
        if min_periods < 0:
            raise Exception('min_periods cannot be less than 0!')

        result[:min_periods] = np.NaN

    output = values.copy()
    output[okLocs] = result

    if biasCorrection is not None:
        if biasCorrection <= 0:
            raise Exception('Bias correction cannot be negative!')

        output *= biasCorrection

    return output

def ewma(arg, com=None, span=None, minCom=0):
    """
    Calculates the rolling exponentially weighted moving average of a series.

    Parameters
    ----------
    arg : Series, DataFrame, or DataMatrix
    com : float. optional
        Center of mass: \alpha = com / (1 + com),
    span : float, optional
        Specify decay in terms of span, \alpha = 2 / (span + 1)
    minCom : int, default 0
        Optionally require that at least a certain number of periods as
        a multiple of the Center of Mass be included in the sample.

    Returns
    -------
    y : type of input argument

    Note
    ----
    Either center of mass or span must be specified

    EWMA is sometimes specified using a "span" parameter s, we have
    have that the decay parameter \alpha is related to the span in the
    following way:

    \alpha = 1 - 2 / (span + 1) = c / (1 + c)

    where c is the center of mass. Given a span, the
    associated center of mass is:

    c = (s - 1) / 2

    So a "20-day EWMA" would have center 9.5
    """
    if com is None and span is None:
        raise Exception("Must pass either com or span")
    elif com is not None and span is not None:
        raise Exception("com and span are mutually exclusive")

    def ewmaFunc(series):
        series[np.isinf(series)] = NaN
        result = _ewma(series, com)

        firstIndex = _first_valid_index(series)

        result[firstIndex : firstIndex + minCom*com] = NaN
        result = Series(result, index=arg.index)
        return result

    if isinstance(arg, Series):
        output = ewmaFunc(arg)
    elif isinstance(arg, DataFrame):
        output = arg.apply(ewmaFunc)
    else:
        output = _ewma(arg, com)
        firstIndex = _first_valid_index(arg)
        output[firstIndex : firstIndex + minCom * com] = NaN

    return output

def _first_valid_index(arr):
    # argmax scans from left
    return notnull(arr).argmax()

def ewmvar(arg, com, minCom = 0, correctBias = True):
    """
    Calculates the rolling exponentially weighted moving variance of a series.

    Parameters
    ----------
    series : Series
    com : integer
        Center of Mass for exponentially weighted moving average
        decay = com / (1 + com) maps center of mass to decay parameter

    minCom : int, default None
        Optionally require that at least a certain number of periods as
        a multiple of the Center of Mass be included in the sample.

    correctBias : boolean
        Use a standard bias correction
    """

    if correctBias:
        biasCorrection = (1.0 + 2.0 * com) / (2.0 * com)
    else:
        biasCorrection = 1.0

    moment2nd = ewma(arg * arg, com=com, minCom=minCom)
    moment1st = ewma(arg, com=com, minCom=minCom)

    return biasCorrection * (moment2nd - moment1st**2)

def ewmvol(arg, com, minCom=0, correctBias = True):
    """
    Calculates the rolling exponentially weighted moving variance of a series.

    Parameters
    ----------
    series : Series
    com : integer
        Center of Mass for exponentially weighted moving average
        decay = com / (1 + com) maps center of mass to decay parameter

    minCom : int, default None
        Optionally require that at least a certain number of periods as
        a multiple of the Center of Mass be included in the sample.

    correctBias : boolean
        Use a standard bias correction
    """
    result = ewmvar(arg, com=com, minCom=minCom, correctBias=correctBias)

    if isinstance(result, DataFrame):
        result = result.apply(np.sqrt)
    else:
        result = np.sqrt(result)

    return result

def ewmcov(seriesA, seriesB, com, minCom=0, correctBias=True):
    """
    Calculates the rolling exponentially weighted moving variance of a
    series.

    Parameters
    ----------
    series : Series
    com : integer
        Center of Mass for exponentially weighted moving average
        decay = com / (1 + com) maps center of mass to decay parameter

    minCom : int, default None
        Optionally require that at least a certain number of periods as
        a multiple of the Center of Mass be included in the sample.

    correctBias : boolean
        Use a standard bias correction
    """

    if correctBias:
        biasCorrection = ( 1.0 + 2.0 * com ) / (2.0 * com)
    else:
        biasCorrection = 1.0

    if not isinstance(seriesB, type(seriesA)):
        raise Exception('Input arrays must be of the same type!')

    if isinstance(seriesA, Series):
        if seriesA.index is not seriesB.index:
            commonIndex = seriesA.index.intersection(seriesB.index)
            seriesA = seriesA.reindex(commonIndex)
            seriesB = seriesB.reindex(commonIndex)

    okLocs = notnull(seriesA) & notnull(seriesB)

    cleanSeriesA = seriesA[okLocs]
    cleanSeriesB = seriesB.reindex(cleanSeriesA.index)

    XY = ewma(cleanSeriesA * cleanSeriesB, com=com, minCom=minCom)
    X  = ewma(cleanSeriesA, com=com, minCom=minCom)
    Y  = ewma(cleanSeriesB, com=com, minCom=minCom)

    return biasCorrection * (XY - X * Y)


def ewmcorr(seriesA, seriesB, com, minCom=0):
    """
    Calculates a rolling exponentially weighted moving correlation of
    2 series.

    Parameters
    ----------
    seriesA : Series
    seriesB : Series
    com : integer
        Center of Mass for exponentially weighted moving average
        decay = com / (1 + com) maps center of mass to decay parameter

    minCom : int, default None
        Optionally require that at least a certain number of periods as
        a multiple of the Center of Mass be included in the sample.
    """
    if not isinstance(seriesB, type(seriesA)):
        raise Exception('Input arrays must be of the same type!')

    if isinstance(seriesA, Series):
        if seriesA.index is not seriesB.index:
            commonIndex = seriesA.index.intersection(seriesB.index)
            seriesA = seriesA.reindex(commonIndex)
            seriesB = seriesB.reindex(commonIndex)

    okLocs = notnull(seriesA) & notnull(seriesB)

    cleanSeriesA = seriesA[okLocs]
    cleanSeriesB = seriesB.reindex(cleanSeriesA.index)

    XY = ewma(cleanSeriesA * cleanSeriesB, com=com, minCom=minCom)
    X  = ewma(cleanSeriesA, com=com, minCom=minCom)
    Y  = ewma(cleanSeriesB, com=com, minCom=minCom)
    varX = ewmvar(cleanSeriesA, com=com, minCom=minCom, correctBias=False)
    varY = ewmvar(cleanSeriesB, com=com, minCom=minCom, correctBias=False)

    return (XY - X * Y) / np.sqrt(varX * varY)

