from cStringIO import StringIO

from numpy import NaN
from numpy.lib.format import write_array, read_array
import numpy as np

from pandas.core.datetools import DateOffset
from pandas.core.frame import DataFrame, _pfixed
from pandas.core.index import Index, NULL_INDEX
from pandas.core.series import Series, remove_na
from pandas.lib.tseries import isnull, notnull
import pandas.lib.tseries as tseries

#-------------------------------------------------------------------------------
# DataMatrix class

class DataMatrix(DataFrame):
    """
    Matrix version of DataFrame, optimized for cross-section operations,
    numerical computation, and other operations that do not require the
    frame to change size.

    Constructor params
    ------------------
    data: numpy ndarray or dict of Series
        Constructor can understand various kinds of inputs
    index: Index or array-like
        Index to use for resulting frame (optional if provided dict of Series)
    columns: Index or array-like
    dtype: dtype, default=float
        Data type to use

    Notes
    -----
    Transposing is much faster in this regime, as is calling getXS, so please
    take note of this.
    """
    values = None
    _columns = None
    _index = None
    objects = None
    def __init__(self, data=None, index=None, columns=None, dtype=None,
                 objects=None):

        def handleDict(data, index, columns, objects, dtype):
            """
            Segregate Series based on type and coerce into matrices.

            Needs to handle a lot of exceptional cases.
            """
            if len(data) == 0:
                if index is None:
                    index = NULL_INDEX
                values = np.empty((len(index), 0), dtype=dtype)
                columns = NULL_INDEX
            else:
                if index is None:
                    s = data.values()[0]
                    if isinstance(s, Series):
                        index = s.index
                    else:
                        index = Index(np.arange(len(s)))

                if not isinstance(index, Index):
                    index = Index(index)

                objectDict = {}
                if objects is not None:
                    objectDict.update(objects)

                valueDict = {}
                for k, v in data.iteritems():
                    # Forces homogoneity
                    if isinstance(v, Series):
                        v = v.reindex(index)
                    else:
                        assert(len(v) == len(index))
                        v = Series(v, index=index)

                    if issubclass(v.dtype.type, (float, int, bool)):
                        valueDict[k] = v
                    else:
                        objectDict[k] = v

                if len(valueDict) == 0:
                    dtype = np.object_
                    valueDict = objectDict
                else:
                    dtype = np.float_
                    if len(objectDict) > 0:
                        objects = DataMatrix(objectDict, dtype=np.object_,
                                             index=index)
                    else:
                        objects = None

                columns = Index(sorted(valueDict))
                values = np.empty((len(index), len(columns)), dtype=dtype)

                for i, col in enumerate(columns):
                    values[:, i] = valueDict[col]

            return index, columns, values, objects

        if isinstance(data, dict):
            index, columns, values, objects = handleDict(data, index,
                                                         columns, objects,
                                                         dtype)
        elif isinstance(data, np.ndarray):
            if data.ndim == 1:
                N = data.shape[0]
                if N == 0:
                    data = data.reshape((data.shape[0], 0))
                else:
                    data = data.reshape((data.shape[0], 1))

            values = np.asarray(data)

        elif data is None:
            if index is None:
                N = 0
                index = NULL_INDEX
            else:
                N = len(index)

            if columns is None:
                K = 0
                columns = NULL_INDEX
            else:
                K = len(columns)

            values = np.empty((N, K), dtype=dtype)
            values[:] = NaN
        else:
            raise Exception('DataMatrix constructor not properly called!')

        if objects is not None:
            if isinstance(objects, DataMatrix):
                if objects.index is not index:
                    self.objects = objects.reindex(index)
            else:
                objects = DataMatrix(objects, index=index)

        self.values = values
        self.index = index
        self.columns = columns
        self.objects = objects

    def __getstate__(self):
        valsIO = StringIO()
        colsIO = StringIO()
        idxIO = StringIO()

        write_array(valsIO, self.values)
        write_array(colsIO, self.columns)
        write_array(idxIO, self.index)

        if self.objects is not None:
            objects = self.objects.__getstate__()
        else:
            objects = None

        return (valsIO.getvalue(), colsIO.getvalue(),
                idxIO.getvalue(), objects)

    def __setstate__(self, state):
        vals, cols, idx, objects = state

        def interpret(s):
            arr = read_array(StringIO(s))
            return arr

        self.values = interpret(vals)
        self.index = interpret(idx)
        self.columns = interpret(cols)

        if objects is not None:
            ovals, ocols, oidx, _ = objects
            self.objects = DataMatrix(interpret(ovals), index=self.index,
                                      columns=interpret(ocols))
        else:
            self.objects = None

#-------------------------------------------------------------------------------
# Alternate constructors

    @classmethod
    def fromDict(cls, inputDict={}, castFloat=True, **kwds):
        """
        Convert a two-level tree representation of a series or time series
        to a DataMatrix.

        tree is structured as:
            {'col1' : {
                idx1 : value1,
                ...
                idxn : valueN
                    },
            ...}
        e.g. tree['returns'][curDate] --> return value for curDate

        Parameters
        ----------
        input: dict object
            Keys become column names of returned frame
        kwds: optionally provide arguments as keywords

        Example
        -------
        df1 = DataMatrix.fromDict(myDict)
        df2 = DataMatrix.fromDict(A=seriesA, B=seriesB)
        """
        inputDict.update(kwds)

        # Get set of indices
        indices = set([])
        for key, branch in inputDict.iteritems():
            indices = indices | set(branch.keys())

        index = Index(sorted(indices))
        # Convert to Series
        series = {}
        for col, mapping in inputDict.iteritems():
            if not isinstance(mapping, Series):
                mapping = Series.fromDict(mapping)
            series[col] = mapping.reindex(index)

        return DataMatrix(series, index=index)

    @classmethod
    def fromMatrix(cls, mat, colNames, rowNames):
        """
        Compatibility method for operations in DataFrame that use
        fromMatrix.

        Parameters
        ----------
        mat: ndarray
            Dimension T x N
        colNames: iterable
            Dimension N
        rowNames: iterable
            Dimension T

        Returns
        -------
        DataMatrix

        See also
        --------
        DataFrame.fromMatrix
        """
        rows, cols = mat.shape
        try:
            assert(rows == len(rowNames))
            assert(cols == len(colNames))
        except AssertionError:
            raise Exception('Dimensions do not match: %s, %s, %s' %
                            (mat.shape, len(rowNames), len(colNames)))

        index = Index(rowNames)
        colIndex = Index(colNames)

        idxMap = colIndex.indexMap

        return DataMatrix(mat, index=index, columns=colIndex)

    @classmethod
    def load(cls, baseFile):
        """
        Load DataMatrix from file.

        Parameters
        ----------
        baseFile: string
            Filename base where index/values are stored.
            e.g. baseFile='myfile' --> 'myfile_index.npy' and
                                       'myfile_values.npy'

        Returns
        -------
        DataMatrix
        """
        import os

        objectsFile = baseFile + '_objects'
        cacheLoad = np.load(baseFile + '.npz')

        if os.path.exists(objectsFile + '.npz'):
            objectData = np.load(objectsFile + '.npz')
            objects = DataMatrix(objectData['v'], columns=objectData['c'],
                                 index=Index(objectData['i']))
        else:
            objects = None

        return DataMatrix(cacheLoad['v'], index=Index(cacheLoad['i']),
                          columns=cacheLoad['c'], objects=objects)

    def save(self, baseFile):
        """
        Write DataFrame efficiently to file using NumPy serialization,
        which is easily 100x faster than cPickle.

        Note
        ----
        Saves data to 3 files, one for index, columns, and values matrix.
        """

        objectsFile = baseFile + '_objects'
        np.savez(baseFile, i=self.index, v=self.values, c=self.columns)

        if self.objects is not None and len(self.objects.columns) > 0:
            self.objects.save(objectsFile)

#-------------------------------------------------------------------------------
# Outputting

    def toCSV(self, path=None, nanRep='', writeMode='wb', index=True,
              header=True, cols=None):
        """
        Write the DataMatrix to a CSV file

        Parameters
        ----------
        path: string
            Output file path
        nanRep: string, default=''
            Appearance of NaN values in output
        index: boolean, default=True
            Prints index if True
        header: boolean, default=True
            Prints header if True
        cols: list of strings
            Prints the values in order specified by cols.
            By default, prints all columns in lexicographical order.
        """
        if path is None:
            import sys
            f = sys.stdout
        else:
            f = open(path, writeMode)
        if cols is None:
            cols = self.cols()
        serDict = self._series

        if header:
            if index:
                f.write(',')
            f.write(','.join([str(c) for c in cols]))
            f.write('\n')
        for i, idx in enumerate(self.index):
            if index:
                f.write(str(idx) + ',')
            for col in cols:
                val = serDict[col].get(idx)
                if isinstance(val, float) and np.isnan(val) == True:
                    val = nanRep
                else:
                    val = str(val)
                f.write(val + ',')
            f.write('\n')
        if path is not None:
            f.close()
        print 'CSV file written successfully: %s' % path

    def toString(self, to_stdout=True, verbose=False,
                 colSpace=15, formatters=None):
        """
        Output a tab-separated version of this DataMatrix
        """
        from cStringIO import StringIO

        output = StringIO()

        if formatters is not None:
            return self._toStringFormatted(formatters)

        mat = self.values
        cols = self.columns
        jinds = range(len(cols))
        totaljinds = range(len(self.cols()))

        if self.objects is None:
            obj_jinds = range(0)
        else:
            obj_jinds = range(len(self.objects.cols()))

        idxSpace = max([len(str(idx)) for idx in self.index]) + 4
        if len(self.cols()) == 0:
            output.write('DataMatrix is empty!\n')
            output.write(self.index.__repr__())

        else:
            output.write(_pfixed('', idxSpace))
            for h in self.cols():
                output.write(_pfixed(h, colSpace))

            output.write('\n')

            for i, idx in enumerate(self.index):
                output.write(_pfixed(idx, idxSpace))
                objcounter = 0
                floatcounter = 0
                for cName in self.cols():
                    if cName in cols:
                        vals = mat[i, floatcounter]
                        output.write(_pfixed(vals, colSpace))
                        floatcounter += 1
                    else:
                        vals = self.objects.values[i, objcounter]
                        output.write(_pfixed(vals, colSpace))
                        objcounter += 1

                output.write('\n')

        if to_stdout:
            print output.getvalue()
        else:
            return output.getvalue()

    def info(self, to_stdout=True):
        """
        Concise summary of a DataMatrix, used in __repr__ when very large.
        """
        if len(self.columns) == 0:
            output = 'DataMatrix is empty!\n'
            output += repr(self.index)
            return output

        output = 'Index: %s entries' % len(self.index)
        if len(self.index) > 0:
            output += ', %s to %s\n' % (self.index[0], self.index[-1])
        else:
            output += '\n'

        output += 'Data columns:\n'
        space = max([len(str(k)) for k in self.columns]) + 4

        isObjects = False
        try:
            counts = isfinite(self.values).sum(0)
        except:
            counts = np.repeat(self.values.shape[0], len(self.columns))
            isObjects = True

        columns = []
        if isObjects:
            for j, col in enumerate(self.columns):
                columns.append('%s%d  non-null values' %
                               (_pfixed(col, space), counts[j]))
        else:
            for j, col in enumerate(self.columns):
                columns.append('%s%d  non-null values' %
                               (_pfixed(col, space), counts[j]))

        if self.objects is not None and len(self.objects.columns) > 0:
            n = len(self.objects.index)
            for col in self.objects:
                line = '%s%d  non-null values' % (_pfixed(col, space), n)
                columns.append(line)

        columns.sort()

        dtypeLine = ''

        nf = len(self.columns)
        df = self.values.dtype
        if self.objects is not None:
            no = len(self.objects.columns)
            do = self.objects.values.dtype
            dtypeLine = '\ndtypes: %s(%d), %s(%d)' % (df, nf, do, no)
        else:
            dtypeLine = '\ndtype: %s(%d)' % (df, nf)

        output += '\n'.join(columns) + dtypeLine

        if to_stdout:
            print output
        else:
            return output

#-------------------------------------------------------------------------------
# Properties for index and columns

    def _get_columns(self):
        return self._columns

    def _set_columns(self, cols):
        if cols is None:
            if self.values is not None and self.values.shape[1] > 0:
                raise Exception('Columns cannot be None here!')
            else:
                self._columns = NULL_INDEX
                return

        if len(cols) != self.values.shape[1]:
            raise Exception('Columns length %d did not match values %d!' %
                            (len(cols), self.values.shape[1]))

        if not isinstance(cols, Index):
            cols = Index(cols)

        self._columns = cols

    columns = property(fget=_get_columns, fset=_set_columns)

    def _set_index(self, index):
        if index is None:
            if self.values is not None and self.values.shape[0] > 0:
                raise Exception('Index cannot be None here!')
            else:
                self._index = NULL_INDEX
                return

        if len(index) > 0:
            if len(index) != self.values.shape[0]:
                raise Exception('Index length %d did not match values %d!' %
                                (len(index), self.values.shape[0]))

        if not isinstance(index, Index):
            index = Index(index)

        self._index = index

    def _get_index(self):
        return self._index

    index = property(fget=_get_index, fset=_set_index)

#-------------------------------------------------------------------------------
# "Magic methods"

    def __nonzero__(self):
        if self.values is not None:
            N, K = self.values.shape
            if N == 0 or K == 0:
                if self.objects is None:
                    return False
                else:
                    return self.objects.__nonzero__()
            else:
                return True
        else:
            if self.objects is None:
                return False
            else:
                return self.objects.__nonzero__()

    def __neg__(self):
        mycopy = self.copy()
        mycopy.values = -mycopy.values
        return mycopy

    def __repr__(self):
        if self.values is None or len(self.columns) == 0:
            output = 'Empty DataMatrix\nIndex: %s' % repr(self.index)
        elif 0 < len(self.index) < 1000 and self.values.shape[1] < 10:
            output = self.toString(to_stdout=False)
        else:
            output = str(self.__class__) + '\n'
            output = output + self.info(to_stdout=False)

        return output

    def __getitem__(self, item):
        """
        Retrieve column, slice, or subset from DataMatrix.

        Possible inputs
        ---------------
        single value: retrieve a column as a Series
        slice: reindex to indices specified by slice
        boolean vector: like slice but more general, reindex to indices
          where the input vector is True

        Examples
        --------
        column = dm['A']

        dmSlice = dm[:20] # First 20 rows

        dmSelect = dm[dm.count(axis=1) > 10]

        Note
        ----
        This is a magic method. Do NOT call explicity.
        """
        if isinstance(item, slice):
            start, stop = item.start, item.stop
            start = 0 if start is None else start
            stop = len(self) if stop is None else stop
            if start < 0:
                start += len(self)
            if stop < 0:
                stop += len(self)

            indexRange = self.index[start:stop]
            if self.objects is not None:
                newObjects = self.objects.reindex(indexRange)
            else:
                newObjects = None

            return DataMatrix(data=self.values[start:stop], index=indexRange,
                              columns=self.columns, objects=newObjects)
        elif isinstance(item, np.ndarray):
            if len(item) != len(self.index):
                raise Exception('Item wrong length %d instead of %d!' %
                                (len(item), len(self.index)))
            newIndex = self.index[item]
            return self.reindex(newIndex)
        else:
            if self.objects is not None and item in self.objects:
                return self.objects[item]
            else:
                return self._getSeries(item)

    _dataTypes = [np.float_, np.bool_, np.int_]
    def __setitem__(self, key, value):
        """
        Add series to DataMatrix in specified column.

        If series is a numpy-array (not a Series/TimeSeries), it must be the
        same length as the DataMatrix's index or an error will be thrown.

        Series/TimeSeries will be conformed to the DataMatrix's index to
        ensure homogeneity.
        """
        import bisect

        isObject = False
        if hasattr(value, '__iter__'):
            if isinstance(value, Series):
                value = np.asarray(value.reindex(self.index))

            else:
                assert(len(value) == len(self.index))

                if not isinstance(value, np.ndarray):
                    value = np.array(value)
                    if value.dtype.type == np.str_:
                        value = np.array(value, dtype=object)
        else:
            try:
                value = np.repeat(value, len(self.index))
            except:
                raise Exception('Could not put %s in the matrix!' % value)

        if value.dtype not in self._dataTypes:
            isObject = True

        if self.values is None:
            if isObject:
                if self.objects is None:
                    self.objects = DataMatrix({key : value},
                                              index=self.index)
                else:
                    self.objects[key] = value
            else:
                self.values = value.reshape((len(value), 1))
                self.columns = Index([key])
            return

        if self.values.dtype == np.object_:
            if key in self.columns:
                loc = self.columns.indexMap[key]
                self.values[:, loc] = value
            elif len(self.columns) == 0:
                self.values = value.reshape((len(value), 1))
                self.columns = Index([key])
            else:
                loc = bisect.bisect_right(self.columns, key)
                if loc == self.values.shape[1]:
                    newValues = np.c_[self.values, value]
                    newColumns = Index(np.concatenate((self.columns, [key])))
                elif loc == 0:
                    newValues = np.c_[value, self.values]
                    newColumns = Index(np.concatenate(([key], self.columns)))
                else:
                    newValues = np.c_[self.values[:, :loc], value,
                                      self.values[:, loc:]]
                    toConcat = (self.columns[:loc], [key], self.columns[loc:])
                    newColumns = Index(np.concatenate(toConcat))
                self.values = newValues
                self.columns = newColumns
        else:
            if key in self.columns:
                loc = self.columns.indexMap[key]
                self.values[:, loc] = value
            elif isObject:
                if self.objects is None:
                    self.objects = DataMatrix({key : value},
                                              index=self.index)
                else:
                    self.objects[key] = value
            elif len(self.columns) == 0:
                self.values = value.reshape((len(value), 1)).astype(np.float)
                self.columns = Index([key])
            else:
                loc = bisect.bisect_right(self.columns, key)
                if loc == self.values.shape[1]:
                    newValues = np.c_[self.values, value]
                    newColumns = Index(np.concatenate((self.columns, [key])))
                elif loc == 0:
                    newValues = np.c_[value, self.values]
                    newColumns = Index(np.concatenate(([key], self.columns)))
                else:
                    newValues = np.c_[self.values[:, :loc], value,
                                      self.values[:, loc:]]
                    toConcat = (self.columns[:loc], [key], self.columns[loc:])
                    newColumns = Index(np.concatenate(toConcat))
                self.values = newValues
                self.columns = newColumns

    def __delitem__(self, key):
        """
        Delete column from DataMatrix
        """
        if key in self.columns:
            loc = self.columns.indexMap[key]
            T, N = self.values.shape
            if loc == N:
                newValues = self.values[:, :loc]
                newColumns = self.columns[:loc]
            else:
                newValues = np.c_[self.values[:, :loc], self.values[:, loc+1:]]
                newColumns = Index(np.concatenate((self.columns[:loc],
                                                   self.columns[loc+1:])))
            self.values = newValues
            self.columns = newColumns

        if self.objects is not None and key in self.objects:
            del self.objects[key]

    def __iter__(self):
        """Iterate over columns of the frame."""
        return iter(self.columns)

    def __contains__(self, key):
        """True if DataMatrix has this column"""
        hasCol = key in self.columns
        if hasCol:
            return True
        else:
            if self.objects is not None and key in self.objects:
                return True
            return False

    def iteritems(self):
        return self._series.iteritems()

#-------------------------------------------------------------------------------
# Helper methods

    # For DataFrame compatibility
    def _getSeries(self, item=None, loc=None):
        if loc is None:
            try:
                loc = self.columns.indexMap[item]
            except KeyError:
                raise Exception('%s not here!' % item)
        return Series(self.values[:, loc], index=self.index)

    def _getSeriesDict(self):
        series = {}
        for i, col in enumerate(self.columns):
            series[col] = self._getSeries(loc=i)
        if self.objects is not None:
            for i, col in enumerate(self.objects.columns):
                series[col] = self.objects._getSeries(loc=i)

        return series
    _series = property(_getSeriesDict)

    def _firstTimeWithNValues(self):
        # Need to test this!
        N = len(self._series)
        selector = (self.count(1) == N)
        if not selector.any():
            raise Exception('No time has %d values!' % N)

        return self.index[selector][0]

    def _withColumns(self, newCols):
        """
        Utility method, force values matrix to have particular columns
        Can make this as cute as we like
        """
        if len(newCols) == 0:
            return DataMatrix(index=self.index)

        T, N = len(self.index), len(newCols)

        resultMatrix = np.empty((T, N), dtype=self.values.dtype)
        resultMatrix.fill(NaN)

        if not isinstance(newCols, Index):
            newCols = Index(newCols)

        overlap = self.columns.intersection(newCols)
        thisIndexer = [self.columns.indexMap[col] for col in overlap]
        resultIndexer = [newCols.indexMap[idx] for idx in overlap]

        resultMatrix[:, resultIndexer] = self.values[:, thisIndexer]

        return DataMatrix(resultMatrix, index=self.index, columns=newCols,
                          objects=self.objects)

    def _combineFrame(self, other, func):
        """
        Methodology, briefly
        - Really concerned here about speed, space

        - Get new index
        - Reindex to new index
        - Determine newColumns and commonColumns
        - Add common columns over all (new) indices
        - Fill to new set of columns

        Could probably deal with some Cython action in here at some point
        """
        if self.index is other.index:
            newIndex = self.index
            myReindex = self
            hisReindex = other
        else:
            newIndex = self.index.union(other.index)
            myReindex = self.reindex(newIndex)
            hisReindex = other.reindex(newIndex)

        if not self and not other:
            return DataMatrix(index=newIndex)
        elif not self:
            return other * NaN
        elif not other:
            return self * NaN

        myValues = myReindex.values
        if self.columns is other.columns:
            newCols = self.columns
            commonCols = self.columns
        else:
            newCols = self.columns.union(other.columns)
            commonCols = self.columns.intersection(other.columns)
        hisValues = hisReindex.values
        hisCols = hisReindex.columns

        if len(newCols) == len(commonCols):
            resultMatrix = func(myValues, hisValues)
        else:
            T, N = len(newIndex), len(newCols)
            resultMatrix = np.empty((T, N), dtype=self.values.dtype)
            resultMatrix.fill(NaN)

            myIndexer = [self.columns.indexMap[idx] for idx in commonCols]
            hisIndexer =  [hisCols.indexMap[idx] for idx in commonCols]
            resultIndexer = [newCols.indexMap[idx] for idx in commonCols]

            resultMatrix[:, resultIndexer] = func(myValues[:, myIndexer],
                                                  hisValues[:, hisIndexer])

        # TODO: deal with objects
        return DataMatrix(resultMatrix, index=newIndex, columns=newCols)

    def _combineSeries(self, other, func):
        newIndex = self.index
        newCols = self.columns
        if self.index._allDates and other.index._allDates:
            # Operate row-wise
            if self.index is other.index:
                newIndex = self.index
            else:
                newIndex = self.index + other.index

            if not self:
                return DataMatrix(index=newIndex)

            other = other.reindex(newIndex).view(np.ndarray)
            myReindex = self.reindex(newIndex)
            resultMatrix = func(myReindex.values.T, other).T
        else:
            if len(other) == 0:
                return self * NaN

            # Operate column-wise
            other = other.reindex(self.columns).view(np.ndarray)
            resultMatrix = func(self.values, other)

        # TODO: deal with objects
        return DataMatrix(resultMatrix, index=newIndex, columns=newCols)

    def _combineFunc(self, other, func):
        """
        Combine DataMatrix objects with other Series- or DataFrame-like objects

        This is the core method used for the overloaded arithmetic methods

        Result hierarchy
        ----------------
        DataMatrix + DataFrame --> DataMatrix
        DataMatrix + DataMatrix --> DataMatrix
        DataMatrix + Series --> DataMatrix
        DataMatrix + constant --> DataMatrix

        The reason for 'upcasting' the result is that if addition succeed,
        we can assume that the input DataFrame was homogeneous.
        """
        newIndex = self.index
        if isinstance(other, DataFrame):
            return self._combineFrame(other, func)

        elif isinstance(other, Series):
            return self._combineSeries(other, func)

        else:
            if not self:
                return self

            # Constant of some kind
            newCols = self.columns
            try:
                resultMatrix = func(self.values, other)
            except:
                raise Exception('Bad operator value: %s' % other)

        # TODO: deal with objects
        return DataMatrix(resultMatrix, index=newIndex, columns=newCols)

#-------------------------------------------------------------------------------
# Public methods

    def asMatrix(self, columns=None):
        """
        Convert the DataMatrix to its Numpy-array matrix representation

        Columns are presented in sorted order unless a specific list
        of columns is provided.

        Parameters
        ----------
        columns: list-like
            columns to use in producing matrix, must all be contained

        Returns
        -------
        ndarray
        """
        if columns is None:
            return self.values.copy()
        else:
            idxMap = self.columns.indexMap
            indexer = [idxMap[col] for col in columns]
            return self.values[:, indexer].copy()

    def cols(self):
        """Return sorted list of frame's columns"""
        if self.objects is not None and len(self.objects.columns) > 0:
            return list(self.columns.union(self.objects.columns))
        else:
            return list(self.columns)

    def copy(self, deep=False):
        """
        Make a deep copy of this DataMatrix
        """
        if self.values is not None:
            valsCopy = self.values.copy()
        else:
            valsCopy = None
        return DataMatrix(valsCopy, index=self.index,
                          columns=self.columns, objects=self.objects)

    def cumsum(self, axis=0, asarray=False):
        """
        Return DataMatrix of cumulative sums over requested axis.

        Parameters
        ----------
        axis: {0, 1}
            0 for row-wise, 1 for column-wise
        asarray: boolean, default False
            Choose to return as ndarray or have index attached
        """
        y = array(self.values, subok=True)
        if not issubclass(y.dtype.type, np.int_):
            y[np.isnan(self.values)] = 0
        theSum = y.cumsum(axis)
        if asarray:
            return theSum
        return DataMatrix(theSum, index=self.index,
                          columns=self.columns, objects=self.objects)

    def dropEmptyRows(self, specificColumns=None):
        """
        Return DataMatrix with rows omitted containing ALL NaN values
        for optionally specified set of columns.

        Parameters
        ----------
        specificColumns: list-like, optional keyword
            Columns to consider in removing NaN values. As a typical
            application, you might provide the list of the columns involved in
            a regression to exclude all the missing data in one shot.

        Returns
        -------
        DataMatrix with rows containing any NaN values deleted
        """
        T, N = self.values.shape

        if specificColumns:
            theCount = self.filterItems(specificColumns).count(axis=1,
                                                               asarray=True)
        else:
            theCount = self.count(axis=1, asarray=True)

        return self.reindex(self.index[theCount > 0])

    def dropIncompleteRows(self, specificColumns=None, minObs=None):
        """
        Return DataFrame with rows omitted containing ANY NaN values for
        optionally specified set of columns.

        Parameters
        ----------
        minObs: int or None (default)
           Instead of requiring all the columns to have observations, require
           only minObs observations
        specificColumns: list-like, optional keyword
            Columns to consider in removing NaN values. As a typical
            application, you might provide the list of the columns involved in
            a regression to exlude all the missing data in one shot.

        Returns
        -------
        This DataFrame with rows containing any NaN values deleted
        """
        T, N = self.values.shape
        if specificColumns:
            cols = self.columns.intersection(specificColumns)
            theCount = self.filterItems(cols).count(axis=1, asarray=True)
            N = len(cols)
        else:
            theCount = self.count(axis=1, asarray=True)

        if minObs is None:
            minObs = N

        return self.reindex(self.index[theCount >= minObs])

    def fill(self, value=None, method='pad'):
        """
        Fill NaN values using the specified method.

        Member Series / TimeSeries are filled separately.

        Parameters
        ----------
        value: any kind (should be same type as array)
            Value to use to fill holes (e.g. 0)

        method: {'backfill', 'pad', None}
            Method to use for filling holes in new inde

        Returns
        -------
        DataMatrix with NaN's filled

        See also
        --------
        reindex, asfreq
        """
        if value is None:
            result = {}
            for col in self._series:
                series = self._series[col]
                filledSeries = series.fill(method=method, value=value)

                result[col] = filledSeries
            return DataMatrix(result, index=self.index, objects=self.objects)
        else:
            def fillfunc(vec):
                vec[isnull(vec)] = value
                return vec

            gotFloat = isinstance(value, (int, float))
            if gotFloat and self.values.dtype == np.float64:
                # Float type values
                if len(self.columns) == 0:
                    return self

                vals = self.values.copy()
                vals[-np.isfinite(self.values)] = value
                objectsToUse = None
                if self.objects is not None:
                    objectsToUse = self.objects.copy()
                return DataMatrix(vals, index=self.index, columns=self.columns,
                                  objects=objectsToUse)

            elif self.values.dtype == np.object_:
                # Object type values
                if len(self.columns) == 0:
                    return self

                myCopy = self.copy()

                vals = myCopy.values
                myCopy.values = np.apply_along_axis(fillfunc, 0, vals)

                return myCopy
            else:
                # Object type values
                if len(self.objects.columns) == 0:
                    return self

                myCopy = self.copy()
                vals = myCopy.objects.values
                myCopy.objects.values = np.apply_along_axis(fillfunc, 0, vals)

                return myCopy

    def getTS(self, colName=None, fromDate=None, toDate=None, nPeriods=None):
        """
        Return a DataMatrix / TimeSeries corresponding to given arguments

        Parameters
        ----------
        colName: string or None
            particular column name requested, fine to leave blank
        fromDate: datetime
        toDate: datetime
        nPeriods: int/float

        Note
        ----
        Error thrown if all of fromDate, toDate, nPeriods specified.

        Returns
        -------
        DataMatrix or TimeSeries
        """
        # Should use bisect in here

        if toDate:
            if toDate not in self.index:
                if toDate > self.index[0]:
                    toDate = self.index.asOfDate(toDate)
                else:
                    raise Exception('End date after last date in this index!')
        if fromDate:
            if fromDate not in self.index:
                if fromDate < self.index[-1]:
                    fromDate = self.index.asOfDate(fromDate)
                else:
                    raise Exception('Begin date after last date in this index!')

        if fromDate and toDate:
            if nPeriods:
                raise Exception('fromDate/toDate, toDate/nPeriods, ' +
                                'fromDate/nPeriods are mutually exclusive')
            beg_slice = self.index.indexMap[fromDate]
            end_slice = self.index.indexMap[toDate] + 1
        elif fromDate and nPeriods:
            beg_slice = self.index.indexMap[fromDate]
            end_slice = self.index.indexMap[fromDate] + nPeriods
        elif toDate and nPeriods:
            beg_slice = self.index.indexMap[toDate] - nPeriods + 1
            end_slice = self.index.indexMap[toDate] + 1
        else:
            raise Exception('Not enough arguments provided to getTS')

        # Fix indices in case they fall out of the boundaries
        beg_slice = max(0, beg_slice)
        end_slice = min(len(self.index), end_slice)
        dateRange = self.index[beg_slice:end_slice]

        if colName:
            return self[colName][beg_slice:end_slice]
        else:
            newValues = self.values[beg_slice:end_slice]

            newLinks = None
            if self.objects is not None and len(self.objects.columns) > 0:
                newLinks = self.objects.reindex(dateRange)

            return DataMatrix(newValues, index=dateRange,
                              columns=self.columns, objects=newLinks)

    def getXS(self, key, subset=None, asOf=False):
        """
        Returns a row from the DataMatrix as a Series object.

        Parameters
        ----------
        key: some index contained in the index
        subset: iterable (list, array, set, etc.), optional
            columns to be included
        asOf: boolean, optional
            Whether to use asOf values for TimeSeries objects
            Won't do anything for Series objects.

        Note
        ----
        Will try to return a TimeSeries if the columns are dates.
        """
        if key not in self.index:
            raise Exception('No cross-section for %s' % key)

        loc = self.index.indexMap[key]

        if subset:
            subset = np.unique(subset)
            indexer = [self.columns.indexMap[col] for col in subset]
            theSlice = self.values[loc, indexer].copy()
            xsIndex = subset
        else:
            theSlice = self.values[loc, :].copy()
            xsIndex = self.columns

        result = Series(theSlice, index=xsIndex)

        if self.objects is not None and len(self.objects.columns) > 0:
            result = result.append(self.objects.getXS(key))

        return result

    def merge(self, otherFrame, on=None):
        """
        Merge DataFrame or DataMatrix with this one on some many-to-one index

        Parameters
        ----------
        otherFrame: DataFrame
            Index should be similar to one of the columns in this one
        on: string
            Column name to use

        Example
        -------
        This frame         Other frame
            c1                 q1
        a   1              0   v1
        b   0              1   v2
        c   1
        d   0
        """
        if len(otherFrame.index) == 0:
            return self

        if on not in self:
            raise Exception('%s column not contained in this frame!' % on)

        otherM = otherFrame.asMatrix()
        indexMap = otherFrame.index.indexMap

        fillVec, mask = tseries.getMergeVec(self[on], indexMap)

        tmpMatrix = otherM[fillVec]
        tmpMatrix[-mask] = NaN

        seriesDict = dict((col, tmpMatrix[:, j])
                           for j, col in enumerate(otherFrame.columns))

        if getattr(otherFrame, 'objects'):
            objects = otherFrame.objects

            objM = objects.asMatrix()
            cols = objects.columns

            tmpMat = objM[fillVec]
            tmpMat[-mask] = NaN
            objDict = dict((col, tmpMat[:, j])
                           for j, col in enumerate(objects.columns))

            seriesDict.update(objDict)

        filledFrame = DataFrame(data=seriesDict, index=self.index)

        return self.leftJoin(filledFrame)

    def reindex(self, newIndex, fillMethod = None):
        """
        Reindex data inside, optionally filling according to some rule.

        Parameters
        ----------
        newIndex:   array-like
            preferably an Index object (to avoid duplicating data)
        fillMethod: {'backfill', 'pad', 'interpolate', None}
            Method to use for filling holes in reindexed DataFrame

        Returns
        -------
        DataMatrix
        """
        if newIndex is self.index:
            return self

        if len(newIndex) == 0:
            return DataMatrix(index=NULL_INDEX)

        if not isinstance(newIndex, Index):
            newIndex = Index(newIndex)

        if len(self.index) == 0:
            return DataMatrix(index=newIndex, columns=self.columns)

        selfM = self.values
        oldMap = self.index.indexMap
        newMap = newIndex.indexMap

        if not fillMethod:
            fillMethod = ''

        fillMethod = fillMethod.upper()

        if fillMethod not in ['BACKFILL', 'PAD', '']:
            raise Exception("Don't recognize fillMethod: %s" % fillMethod)

        fillVec, mask = tseries.getFillVec(self.index, newIndex, oldMap,
                                           newMap, fillMethod)

        tmpMatrix = selfM[fillVec]
        tmpMatrix[-mask] = NaN

        if self.objects is not None and len(self.objects.columns) > 0:
            newLinks = self.objects.reindex(newIndex)
        else:
            newLinks = None

        return DataMatrix(tmpMatrix, index=newIndex,
                          columns=self.columns, objects=newLinks)

    @property
    def T(self):
        """
        Returns a DataMatrix with the rows/columns switched.
        """
        if self.objects is not None:
            objectsT = self.objects.values.T
            valuesT = self.values.T
            newValues = np.concatenate((valuesT, objectsT), axis=0)
            newIndex = Index(np.concatenate((self.columns,
                                             self.objects.columns)))

            return DataMatrix(newValues, index=newIndex, columns=self.index)
        else:
            return DataMatrix(data=self.values.T, index=self.columns,
                              columns=self.index)

    def shift(self, periods, offset=None):
        """
        Shift the underlying series of the DataMatrix and Series objects within
        by given number (positive or negative) of business/weekdays.

        Parameters
        ----------
        periods: int (+ or -)
            Number of periods to move
        offset: DateOffset, optional
            Increment to use from datetools module

        Returns
        -------
        DataMatrix
        """
        if periods == 0:
            return self

        if offset is None:
            if periods > 0:
                newIndex = self.index[periods:]
                newValues = self.values[:-periods].copy()
            else:
                newIndex = self.index[:periods]
                newValues = self.values[-periods:].copy()
        else:
            offset = periods * offset
            newIndex = Index([idx + offset for idx in self.index])
            newValues = self.values.copy()
        return DataMatrix(data=newValues, index=newIndex, columns=self.columns)

    def apply(self, func, axis=0):
        """
        Applies func to columns (Series) of this DataMatrix and returns either
        a DataMatrix (if the function produces another series) or a Series
        indexed on the column names of the DataFrame if the function produces
        a value.

        Parameters
        ----------
        func: function
            Function to apply to each column

        Example
        -------

            >>> df.apply(numpy.sqrt) --> DataMatrix
            >>> df.apply(numpy.sum) --> Series

        N.B.: Do NOT use functions that might toy with the index.
        """
        if not len(self.cols()):
            return self

        results = {}

        if isinstance(func, np.ufunc):
            results = func(self.values)
        else:
            if axis == 0:
                results = dict([(k, func(v)) for k, v in self.iteritems()])
            elif axis == 1:
                results = dict([(k, func(v)) for k, v in self.T.iteritems()])

        if isinstance(results, np.ndarray):
            return DataMatrix(data=results, index=self.index,
                              columns=self.columns, objects=self.objects)
        elif isinstance(results, dict):
            if isinstance(results.values()[0], np.ndarray):
                return DataMatrix(results, objects=self.objects)
            else:
                return Series.fromDict(results)
        else:
            raise Exception('This is ridiculous')

    def tapply(self, func):
        """
        Apply func to the transposed DataMatrix, results as per above.
        """
        return self.apply(func, axis=1)

    def applymap(self, func):
        """
        Apply a function to a DataMatrix that is intended to operate
        elementwise, i.e. like doing
            map(func, series) for each series in the DataMatrix

        Parameters
        ----------
        func: function
            Python function, returns a single value from a single value

        Note: try to avoid using this function if you can, very slow.
        """
        npfunc = np.frompyfunc(func, 1, 1)
        results = npfunc(self.values)
        try:
            results = results.astype(self.values.dtype)
        except:
            return DataFrame.fromMatrix(results, self.columns, self.index)
        return DataMatrix(data=results, index=self.index, columns=self.columns)

    # Utility methods

    def filterItems(self, items):
        """
        Restrict frame's columns to input set of items.

        Parameters
        ----------
        items: list-like
            List of columns to restrict to (must not all be present)

        Returns
        -------
        DataMatrix with filtered columns
        """
        if len(self.columns) == 0:
            return self
        intersection = self.columns.intersection(items)
        indexer = [self.columns.indexMap[col] for col in intersection]
        newValues = self.values[:, indexer].copy()
        return DataMatrix(newValues, index=self.index, columns=intersection)

    def filterLike(self, arg):
        """
        Filter to columns partially matching the import argument.

        Keep columns where "arg in col == True"

        Parameter
        ---------
        arg: string

        Return
        ------
        DataMatrix with matching columns
        """
        newCols = Index([c for c in self.columns if arg in c])
        return self._withColumns(newCols)

    def combineFirst(self, otherFrame):
        """
        Combine two DataFrame / DataMatrix objects and default to value
        in frame calling the method.

        Example: a.combineFirst(b)
            a's values prioritized, use values from b to fill holes

        Parameters
        ----------
        otherFrame: DataFrame / Matrix

        Returns
        -------
        DataMatrix
        """
        if not otherFrame:
            return self

        if not self:
            return otherFrame

        if self.index is not otherFrame.index:
            unionIndex = self.index + otherFrame.index
            frame = self.reindex(unionIndex)
            otherFrame = otherFrame.reindex(unionIndex)
        else:
            unionIndex = self.index
            frame = self

        result = {}
        for col, series in frame.iteritems():
            otherSeries = otherFrame[col] if col in otherFrame else None
            if otherSeries is not None:
                result[col] = series.__class__(np.where(isnull(series),
                                                        otherSeries, series),
                                               index=unionIndex)
            else:
                result[col] = series

        for col, series in otherFrame.iteritems():
            if col not in self:
                result[col] = series

        return DataMatrix(result, index = unionIndex)

    def combineAdd(self, otherFrame):
        """
        Add two DataFrame / DataMatrix objects and do not propagate NaN values,
        so if for a (column, time) one frame is missing a value, it will
        default to the other frame's value (which might be NaN as well)

        Parameters
        ----------
        otherFrame: DataFrame / Matrix

        Returns
        -------
        DataMatrix
        """
        if not otherFrame:
            return self

        if not self:
            return otherFrame

        if self.index is not otherFrame.index:
            unionIndex = self.index + otherFrame.index
            frame = self.reindex(unionIndex)
            otherFrame = otherFrame.reindex(unionIndex)
        else:
            unionIndex = self.index
            frame = self

        unionCols = sorted(set(frame.cols() + otherFrame.cols()))

        result = {}
        for col in unionCols:
            if col in frame and col in otherFrame:
                series = frame[col].view(ndarray)
                otherSeries = otherFrame[col].view(ndarray)
                sok = np.isfinite(series)
                ook = np.isfinite(otherSeries)

                result[col] = np.where(sok & ook, series + otherSeries,
                                       np.where(sok, series, otherSeries))

            elif col in frame:
                result[col] = frame[col]
            elif col in otherFrame:
                result[col]= otherFrame[col]
            else:
                raise Exception('Phantom column, be very afraid')

        return DataMatrix(result, index=unionIndex, columns=unionCols)

    # TODO, works though.
    def outerJoin(self, *frames):
        """
        Form union of input frames.

        Columns must not overlap. Returns a copy.

        Parameters
        ----------
        *frames: list-like
            List of frames (DataMatrix or DataFrame) as function arguments

        Returns
        -------
        DataMatrix
        """
        mergedSeries = self._series.copy()

        unionIndex = self.index
        for frame in frames:
            unionIndex  = unionIndex + frame.index

        for frame in frames:
            for col, series in frame.iteritems():
                if col in mergedSeries:
                    raise Exception('Overlapping columns!')
                mergedSeries[col] = series

        return DataMatrix.fromDict(mergedSeries)

    def leftJoin(self, *frames, **kwds):
        """
        Insert columns of input DataFrames / dicts into this one.

        Columns must not overlap. Returns a copy.

        Parameters
        ----------
        *frames: list-like
            List of frames (DataMatrix or DataFrame) as function arguments

        Keyword args
        ------------
        coerceTo: type or dtype

        Returns
        -------
        DataMatrix
        """

        unionCols = set(self.columns)
        frames = list(frames)

        for frame in frames:
            cols = set(frame.columns)
            if any(unionCols & cols):
                raise Exception('Overlapping columns!')
            unionCols |= cols

        newColumns = Index(sorted(unionCols))
        seriesDict = self._series

        for frame in frames:
            frame = frame.reindex(self.index)
            seriesDict.update(frame._series)

        return DataMatrix(seriesDict, index=self.index)

    def append(self, otherFrame):
        if not otherFrame:
            return self
        if not self:
            return otherFrame
        if (isinstance(otherFrame, DataMatrix) and
            list(self.columns) == list(otherFrame.columns)):
            #if len(self.index.diff(otherFrame.index)) != len(self.index):
            #    raise ValueError('Index cannot overlap')
            idx = Index(np.concatenate([self.index, otherFrame.index]))
            mat = np.vstack((self.values, otherFrame.values))
            dm = DataMatrix(mat, idx, self.columns)
            if otherFrame.objects is None:
                dm.objects = self.objects
            elif self.objects is None:
                dm.objects = otherFrame.objects
            else:
                dm.objects = self.objects.append(otherFrame.objects)
            return dm
        else:
            return super(DataMatrix, self).append(otherFrame)
