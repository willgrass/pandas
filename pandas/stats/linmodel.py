"""Objects for doing linear / pooled xs linear modeling"""

from pandas.core.index import Index
from pandas.core.series import Series
from pandas.core.frame import DataFrame
from datetime import datetime

import numpy.linalg as L
import numpy as np

__all__ = ['LinearModel', 'XSLinearModel', 'regress']

def parseFormula(formString):
    """
    From an R-style formula string, derive a scipy.stats.models formula

    Use 'I' to specify an intercept

    Example: Y ~ X1 + X2 + X3 + I
    """
    from scipy.stats.models.formula import Term, Formula, I

    lhs, rhs = formString.split('~')
    rhsVars = [s.strip() for s in rhs.split('+')]
    newForm = None
    for var in rhsVars:
        if var == 'I':
            term = I
        else:
            term = Term(var)
        newForm = newForm + term if newForm else Formula(term)

    return lhs.strip(), newForm

def _robustlm(formula, lhs):
    from scipy.stats.models import rlm
    from scipy.stats.models.robust.norms import HuberT

    model = rlm(design=formula.design(), M=HuberT())
    result = model.fit(lhs)
    return {
        'beta'      : Series(result.beta, index=formula.names()),
        'tstat'     : Series(result.t(), index=formula.names()),
        'resid'     : Series(result.resid, index=formula.namespace.index),
        'rsquare'   : result.Rsq()
    }

def RLM(X, Y):
    from scipy.stats.models import rlm
    from scipy.stats.models.robust.norms import HuberT

    model = rlm(design=X, M=HuberT())
    result = model.fit(Y)

    return result

def OLS(X, Y):
    from scipy.stats import linregress
    from scipy.stats.models.regression import OLSModel, RegressionResults

    if X.ndim == 1:
        beta, alpha, r, prob, stderr = np.array([linregress(X, Y)[0]])

        result = RegressionResults(beta, X)
        # resid = lhs - X * result.beta
    else:
        model = OLSModel(design=X)
        result = model.fit(Y)

    return result

def Rsquared(resid, lhs, rhsNo):
    regular = 1 - resid.var(ddof=1) / lhs.var(ddof=1)
    N = len(resid)
    adjusted = 1 - (1 - regular) * (N-1) / (N - rhsNo)
    return regular, adjusted

def _ols(formula, lhs):
    from scipy.stats import linregress
    from scipy.stats.models.regression import OLSModel, RegressionResults

    design = formula.design()
    if design.ndim == 1:
        result = RegressionResults(np.array([linregress(design, lhs)[0]]), design)
        resid = Series(lhs - design * result.beta, formula.namespace.index)

        return {
            'beta'  : Series(result.beta, index = formula.names()),
            'resid' : resid
        }

    else:
        model = OLSModel(design=design)
        result = model.fit(lhs)

        resid = Series(result.resid, index=formula.namespace.index)

        returnValue =  {
            'beta'      : Series(result.beta, index=formula.names()),
            'tstat'     : Series(result.t(), index=formula.names()),
            'resid'     : resid,
            'rsquare'   : result.Rsq()
        }

    return returnValue

_funcMap = {
    'ols'       : OLS,
    'rlm'       : RLM,
}

class LinearModel(object):
    def __init__(self, data=None, kind='ols', window = 0, minPeriods=None,
                 nwLags=None, nwDownweight=True, storeFullResid=False,
                 computeForecastStats=False):
        """
        A general class for formulating, fitting a linear TS or XS model.
        For this, it's assumed that the data is indexed on time.

        Parameters
        ----------
        data: DataFrame or dict of arrays.
            For subclasses may be a dict of DataFrame objects, but that's
            too complicated for this part.

        kind: {'ols', 'rlm'}, default is 'ols'
            Specifies scipy.stats.models or RPy routine to use for
            fitting the model. Ex. 'ols', 'rlm', etc.

        window: rolling window size for regression.
            For an XS model (see subclass), this is the number of days to pool.
            For a time series model this is just the standard window.
            NOTE: use window = 0 for expanding window.

        nwLags: int
            Compute Newey-West adjusted T-stat (for reducing autocorrelation)
            By default NOT enabled (as time consuming)

        nwDownweight: boolean (default=True)
            Downweight subsequent lags in Newey-West adjustment
        """
        self.data = data
        self.kind = kind
        self.window = window
        self.minPeriods = minPeriods
        self.nwLags = nwLags
        self.nwDownweight = nwDownweight
        self.storeFullResid = storeFullResid
        self.computeForecastStats = computeForecastStats
        self.forecasts = {}     # store 1-period forecasts
        self._betas = {}       # hidden variables for model results.
        self._tstats = {}
        self._nwTstats = {}
        self._resid = {}
        self._r2 = {}
        self._r2Adjusted = {}
        self._forecastMean = {}
        self._forecastVol = {}

        self.formula = None

    def clear(self):
        self._tstats.clear()
        self._nwTstats.clear()
        self._betas.clear()
        self._resid.clear()
        self._r2.clear()
        self._r2Adjusted.clear()

    def addLags(self, field, number, addToFormula = False):
        """
        Add # of lags of some field to model.

        Lag names will take the standard form 'field_L#', where # is
        the period lag being added.

        Note that this method works if the data is a dict of DataFrames
        """
        from scipy.stats.models.formula import Term

        data = self.data
        for i in range(1, number + 1):
            colName = field + '_L' + str(i)

            data[colName] = data[field].shift(i, strict=True)
            if addToFormula:
                self.formula += Term(colName)

    def parseFormula(self, formString):
        """
        From an R-style formula string, derive a scipy.stats.models formula

        Use 'I' to specify an intercept

        Example: Y ~ X1 + X2 + X3 + I
        """
        from scipy.stats.models.formula import Term, Formula, I

        self.clear()
        self._formString = formString

        lhs, rhs = formString.split('~')
        rhsVars = [s.strip() for s in rhs.split('+')]
        newForm = None
        for var in rhsVars:
            if var == 'I':
                term = I
            else:
                term = Term(var)
            newForm = newForm + term if newForm else Formula(term)
        self.formula = newForm
        self.lhs = lhs.strip()

    def fit(self, index=None, verbose=False, firstPeriod = None, offset = None):
        """
        Fit the model and return a result object.
        """
        if self.formula is None:
            raise Exception('Need to call parseFormula to specify the model!')

        if index is None:
            estPeriods = self.data.index
        else:
            estPeriods = [index]

        if firstPeriod is not None:
            estPeriods = [d for d in estPeriods if d > firstPeriod]

        idxMap = self.data.index.indexMap

        if not hasattr(self, 'formula'):
            raise Exception('Need to call parseFormula before calling fit!')

        formula = self.formula
        formulaNames = formula.names()

        # Function which performs the regression, returns results in nice form
        regFunc = _funcMap[self.kind]
        window = self.window if self.window > 0 else len(self.data.index)

        for period in estPeriods:
            try:
                if verbose:
                    print period
                curSlice = self.data.getTS(toDate=period, nPeriods = window)

                regCols = [x for x in formula.names() if x != 'intercept']
                regCols.append(self.lhs)
                curSlice = curSlice.dropIncompleteRows(specificColumns=regCols)

                if self.minPeriods and len(curSlice.index) < self.minPeriods:
                    continue

                if len(curSlice.index) <= len(formula.names()):
                    continue

                formula.namespace = curSlice

                LHS = curSlice[self.lhs]
                RHS = formula.design()

                result = regFunc(RHS, LHS)

                resid = result.resid
                reg, adj = Rsquared(resid, LHS, len(formulaNames))

                beta = Series(result.beta, index=formulaNames)
                tstat = Series(result.t(), index=formulaNames)

                self._betas[period] = beta
                self._tstats[period] = tstat
                self._r2[period] = reg
                self._r2Adjusted[period] = adj

                if self.computeForecastStats:
                    self._forecastMean[period] = LHS.mean()

                    covX = np.cov(RHS.T)
                    theVol = np.sqrt(np.dot(beta, np.dot(covX, beta)))
                    self._forecastVol[period] = theVol

                if self.nwLags is not None:
                    self._nwTstats[period] = self._calcNWTstats(RHS, result)

                if self.storeFullResid:
                    self._resid[period] = resid
                else:
                    self._resid[period] = result.resid[period]
            except:
                pass
                #print '%s failed.' % period

    def _calcNWTstats(self, design, result):
        from numpy import diag, dot, sqrt

        resids = result['resid'].view(np.ndarray)

        m = (design.T * resids).T
        Xeps = np.dot(m.T, m)

        if self.nwLags > 0:
            for lag in range(1, self.nwLags + 1):
                autoCov = np.dot(m[:-lag].T, m[lag:])

                if self.nwDownweight:
                    weight = lag / (self.nwLags + 1.)
                else:
                    weight = 0

                Xeps = Xeps + (1 - weight) * (autoCov + autoCov.T)

        xxinv = L.inv(np.dot(design.T, design))

        return result['beta'] / sqrt(diag(dot(xxinv, dot(Xeps, xxinv))))

    def tstat(self, period = None):
        if period is not None:
            return self._tstats[period]
        else:
            return DataFrame.fromDict(self._tstats).T

    def nwTstat(self, period = None):
        if period is not None:
            return self._nwTstats[period]
        else:
            return DataFrame.fromDict(self._nwTstats)

    def rsquare(self, period = None):
        if period is not None:
            return self._r2.get(period)
        else:
            return Series.fromDict(self._r2)

    def rsquareAdjusted(self, period = None):
        if period is not None:
            return self._r2Adjusted.get(period)
        else:
            return Series.fromDict(self._r2Adjusted)

    def beta(self, period = None):
        if period is not None:
            return self._betas[period]
        else:
            return DataFrame.fromDict(self._betas).T

    def resid(self, period = None):
        if period is not None:
            return self._resid[period]
        else:
            return Series.fromDict(self._resid)

    def forecastMean(self, period=None):
        if period is not None:
            return self._forecastMean[period]
        else:
            return Series.fromDict(self._forecastMean)

    def forecastVol(self, period=None):
        if period is not None:
            return self._forecastVol[period]
        else:
            return Series.fromDict(self._forecastVol)

    def scatter(self, date, plotFit=True, plotNow=True, axes=None):
        """
        For a UNIVARIATE regression, plot X vs. Y with trendline and
        latest point highlighted.
        """

        from pylab import figure, scatter, xlabel, ylabel, plot, legend
        from scipy.stats.models.regression import OLSModel
        window = self.window if self.window > 0 else len(self.data.index)
        colNames = [x for x in self.formula.names() if x != 'intercept']
        colNames.append(self.lhs)

        curSlice = self.data.getTS(toDate=date, nPeriods = window)
        curSlice = curSlice.dropIncompleteRows(specificColumns = colNames)

        rhsVars = self.formula.names()

        if len(rhsVars) > 2:
            raise Exception('Too many RHS vars!')

        rhsVar, = [x for x in rhsVars if x != 'intercept']

        self.formula.namespace = curSlice

        RHS = curSlice[rhsVar]
        LHS = curSlice[self.lhs]

        if axes is None:
            fig = figure()
            axes = fig.add_subplot(1, 1, 1)

        if plotNow:
            lastX, lastY = RHS[-1:], LHS[-1:]
            axes.plot(lastX, lastY, 'mo', ms=12, label='NOW')
            axes.legend()

        axes.scatter(RHS, LHS)
        axes.xlabel(rhsVar)
        axes.ylabel(self.lhs)

        if plotFit:
            design = self.formula.design()
            model = OLSModel(design=design)
            result =  model.fit(LHS)
            print 'beta: ' + str(result.beta)
            axes.plot(RHS, result.predictors(design), 'b-')

    def summary(self, period):
        """
        Print the summary for a particular date.
        """
        if period not in self._betas:
            self.fit(period)

        results = DataFrame.fromDict(Tstat=self._tstats[period],
                                     Beta=self._betas[period])
        results = results.toString(to_stdout=False)

        rsq = 'R-square: %.5f' % self._r2[period]

        print '\n\n'.join(('Formula: ' + self._formString, results, rsq))


class XSLinearModel(LinearModel):
    """
    A subclass of LinearModel which supports cross-sectional (inc. pooled)
    panel regressions.

    Parameters
    ----------
    data: dict
        Collection of DataFrames
    kind: {'ols', 'rlm'}, default is 'ols'
        Specifies scipy.stats.models routine to use for
        fitting the model. Ex. 'ols', 'rlm', etc.
    window: int
        rolling window size for regression / number of days to pool
        Use window = 1 for standard Fama-Macbeth regression
        Use window = 0 for expanding window (default).
    nwLags: int
        Compute Newey-West adjusted T-stat (for reducing autocorrelation)
        By default NOT enabled (as time consuming)
    nwDownweight: boolean (default=True)
        Downweight subsequent lags in Newey-West adjustment
    minPeriods: int
        minimum number of periods to require for regression
    useFixedEffects: boolean (default=False)
       Add fixed effects dummies on the RHS. These will be N-1 0-1 vectors
       for each item included in the regression, for item X, it will
       be 1 on rows for that item.
    """
    def __init__(self, data=None, kind='ols', window = 0, demeaned=False,
                 nwLags = None, nwDownweight = True, minPeriods=0,
                 useFixedEffects=False):
        # Going to contain all the stacked data for the regression.
        self.stackedFrame = None

        self.useFixedEffects = useFixedEffects

        self._dummies = None  # Store dummies

        # Stores indices needed for slicing the stacked frame
        self.begSlice = {}
        self.endSlice = {}
        self.demeaned = demeaned

        LinearModel.__init__(self, data=data, kind=kind, window=window,
                             minPeriods=minPeriods, nwLags=nwLags,
                             nwDownweight=nwDownweight)

    def parseFormula(self, formString):
        from scipy.stats.models.formula import Term, Formula, I

        LinearModel.parseFormula(self, formString)

        if self.useFixedEffects:
            for dummy in self._dummies:
                term = 'FE_' + dummy

                self.formula = self.formula + Term(term)

            if 'intercept' in self.formula.names() and self.demeaned:
                self.formula = self.formula - I

    parseFormula.__doc__ = LinearModel.parseFormula.__doc__

    def _set_data(self, data):
        """
        We need to be very careful with processing this data because
        the frames in the dict may have different columns, different
        indices, we need to be able to handle this case, seems more likely
        than not.
        """
        from itertools import imap

        if type(data) != dict:
            raise Exception('Data needs to be a dict of DataFrames!')

        stackedData = {}
        periods = set([])
        for key, frame in data.iteritems():
            periods = periods | set(frame.index)
            stackedData[key] = frame.stack()

        # Now convert to DataFrame, drop rows with NA
        stackedFrame = DataFrame.fromDict(stackedData).dropIncompleteRows()

        # Ensure that indices are sorted.
        stackedFrame.sortUp()

        self.begSlice.clear()
        self.endSlice.clear()

        splitIndex = zip(*(x.split(';') for x in stackedFrame.index))
        dateStrings, items = splitIndex

        curDate = None
        for j, dateStr in enumerate(dateStrings):
            if curDate is None:
                thisDate = datetime.fromordinal(int(dateStr))
                self.begSlice[thisDate] = j
                curDate = dateStr
            if dateStr > curDate:
                thisDate = datetime.fromordinal(int(dateStr))
                self.endSlice[datetime.fromordinal(int(curDate))] = j
                self.begSlice[thisDate] = j
                curDate = dateStr
        # Put in the final slice index just for completeness sake.
        self.endSlice[datetime.fromordinal(int(dateStr))] = j + 1


        #    Demean the data cross-sectionally for each date if specified
        #
        #    Data is represented like this:
        #
        #                        Var1           Var2           Var3
        #    20080602;A          4.86406        4.347          4.226
        #    20080602;B          0.91938        1.788          1.378
        #    20080602;C          5.86813        4.955          4.884
        #    20080602;D          2.67625        3.959          3.273
        #    20080603;A          4.86281        4.427          4.312
        #    20080603;B          0.92           1.72           1.266
        #    20080603;C          5.86563        5.035          4.917
        #    20080603;D          2.67313        3.896          3.188
        #    20080604;A          4.86188        4.384          4.253
        #    20080604;B          0.92           1.775          1.325
        #
        #    We group the DataFrame by the string to the left of the ; in each
        #    index, being the date.
        #
        #        grouper function: lambda x: x.split(';')[0]
        #
        #    For each sub-DataFrame, we subtract the mean of each column,
        #    which is the cross-sectional mean for that day.
        #
        #        function to apply: lambda subf: subf - subf.apply(mean)

        if self.useFixedEffects:
            itemSet = sorted(set(items))
            labels = dict(((v, k) for k, v in enumerate(itemSet)))

            labelVector = np.array([labels[x] for x in items], dtype=int)

            for c in itemSet[1:]:
                dummy = (labelVector == labels[c]).astype(float)
                stackedFrame['FE_' + c] = dummy

            self._dummies = itemSet[1:]

        if self.demeaned:
            grouper = lambda x: x.split(';')[0]
            demean = lambda subf: subf - subf.apply(np.mean)
            stackedFrame = stackedFrame.groupby(grouper).transform(demean)

        self.stackedFrame = stackedFrame

        # All periods
        self.periods = Index(sorted(self.begSlice.keys()))

        self.__data = data

    def _get_data(self):
        return self.__data

    _data_doc = """
    Managed property for the 'data' attribute, when a new set of data is
    assigned, created the stacked panel and populates the slicing maps.
    """

    data = property(fset=_set_data, fget=_get_data, doc=_data_doc)

    def resid(self, period = None):
        if period is not None:
            return self._resid[period]
        else:
            return DataFrame.fromDict(self._resid).T

    def getDataSlice(self, period1, period2, colName = None):
        begin = self.begSlice[period1]

        try:
            end = self.endSlice[period2]
        except:
            period2 = max((k for k in self.endSlice.keys() if k < period2))
            end = self.endSlice[period2]

        if colName is not None:
            return self.stackedFrame[colName][begin : end]

        indexRange = self.stackedFrame.index[begin:end]

        newColumns = {}
        for col, series in self.stackedFrame.iteritems():
            newColumns[col] = series[begin:end]
        return DataFrame(data=newColumns, index=indexRange)

    def fit(self, index = None, verbose = False):
        """
        Fit cross-sectional linear model for given period, possibly pooled.
        """
        if self.formula is None:
            raise Exception('Need to call parseFormula to specify the model!')

        if index is None:
            estPeriods = self.periods
        else:
            estPeriods = [index]

        idxMap = self.periods.indexMap

        formula = self.formula
        formulaNames = self.formula.names()

        # Function which performs the regression, returns results in nice form
        regFunc = _funcMap[self.kind]

        window = self.window if self.window > 0 else len(self.periods)

        minPeriods = self.minPeriods

        for it, period in enumerate(estPeriods):
            # Do we have minPeriods worth of data?
            if minPeriods > 0:
                if max(idxMap[period], 0) < minPeriods - 1:
                    continue

            firstPeriod = self.periods[max(idxMap[period] - window + 1, 0)]

            curSlice = self.getDataSlice(firstPeriod, period)

            if len(curSlice.index) <= len(formula.names()):
                continue

            formula.namespace = curSlice

            LHS = curSlice[self.lhs]
            RHS = formula.design()

            result = regFunc(RHS, LHS)
            resid = result.resid

            reg, adj = Rsquared(resid, LHS, len(formulaNames))

            beta = Series(result.beta, index=formulaNames)
            tstat = Series(result.t(), index=formulaNames)

            self._betas[period] = beta
            self._tstats[period] = tstat
            self._r2[period] = reg
            self._r2Adjusted[period] = adj

            if self.nwLags is not None:
                self._nwTstats[period] = self._calcNWTstats(curSlice, RHS,
                                                               beta, resid)

            try:
                oneDaySlice = self.getDataSlice(period, period)
                unstacked = resid.reindex(oneDaySlice.index).unstack()
                self._resid[period] = unstacked[period]
            except:
                raise

    def _calcNWTstats(self, panelSlice, design, beta, resids):
        """
        Calculate Newey-West t-statistics for the panel, handles each set
        of items independently in case the observations are not evenly
        spread out.
        """
        from numpy import diag, dot, sqrt
        from pandas.core.pytools import groupby

        resids = resids.view(np.ndarray)
        t, n = design.shape
        Xeps = np.zeros((n, n))

        for item, indices in groupby(panelSlice.index, lambda x: x.split(';')[1]):
            ix = [panelSlice.index.indexMap[idx] for idx in indices]
            m = (design[ix].T * resids[ix]).T
            nwCov = np.dot(m.T, m)

            if self.nwLags > 0:
                for lag in range(1, self.nwLags + 1):
                    autoCov = np.dot(m[:-lag].T, m[lag:])
                    if self.nwDownweight:
                        weight = lag / (self.nwLags + 1.)
                    else:
                        weight = 0
                    nwCov = nwCov + (1 - weight) * (autoCov + autoCov.T)
            Xeps += nwCov

        xxinv = L.inv(dot(design.T, design))

        return beta / sqrt(diag(dot(xxinv, dot(Xeps, xxinv))))

    def scatter(self, **kwargs):
        raise Exception('Scatter plot disabled for XSLinearModel!')
