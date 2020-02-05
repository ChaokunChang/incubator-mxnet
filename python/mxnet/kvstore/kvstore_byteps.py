# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# coding: utf-8
""" BytePS backend for MXNet KVStore"""
from __future__ import absolute_import

from array import array
import ctypes
import pickle
from ..ndarray import NDArray
from ..ndarray import _ndarray_cls
from ..base import _LIB, c_str_array, c_handle_array, c_array, c_array_buf, c_str
from ..base import check_call, string_types, mx_uint, py_str
from ..base import NDArrayHandle
from .. import optimizer as opt
from .base import KVStoreBase

__all__ = ['BytePS']

from mxnet.log import get_logger
import logging,os
logger = get_logger("Byteps-Backend-Test", level=logging.DEBUG)

@KVStoreBase.register
class BytePS(KVStoreBase):
    """BytePS backend for MXNet KVStore interface."""

    def __init__(self):
        """Initializes a new KVStore."""
        try:
            import byteps.mxnet as bps
            self.handle = bps
        except ImportError as err:
            print('Did not find BytePS library. Please install BytePS first')
            raise err
        # import os
        # logger.debug("totoal workers: {}".format(self.handle.local_size()))
        # logger.debug("Begin init byteps.mxnet for rank {0}".format(self.local_rank))
        logger.debug("BytePS-KVStore ENV:  ",os.environ)
        # os.environ['BYTEPS_LOCAL_RANK'] = str(self.local_rank)
        # os.environ['BYTEPS_LOCAL_SIZE'] = str(self.handle.local_size())
        self.handle.init()
        logger.debug("Byteps- localrank={}, size={}, rank={}".format(self.local_rank, self.num_workers, self.rank))

    def broadcast(self, key, value, out, priority=0):
        """ Broadcast the value NDArray at rank 0 to all ranks' out. If out is None,
        the result is stored in `value`.
        Parameters
        ----------
        key : str, or int
            The keys.
        value : NDArray, or list of NDArray
            Values corresponding to the key.
        out : NDArray, or lise of NDArray
            Values corresponding to the keys.
        Examples
        --------
        >>> # broadcast a single key-value pair
        >>> shape = (2,3)
        >>> kv = mx.kv.create('byteps')
        >>> a = mx.nd.zeros(shape)
        >>> kv.broadcast('3', mx.nd.ones(shape)*2, out=a)
        >>> print a.asnumpy()
        [[ 2.  2.  2.]
        [ 2.  2.  2.]]
        """
        logger.debug("kv.broad_cast is called with key={}, value={}, out={}. ".format(key,value,out))

        # do not accept list or tuple for key/value
        assert isinstance(key, (str, int))		
        # assert isinstance(value, NDArray), type(value)

        # unpack the list if it contains just one NDArray
        value = value[0] if isinstance(value, list) and len(value) == 1 else value
        logger.debug("call byteps_declare_tensor.")
        self.handle.byteps_declare_tensor(str(key))
        logger.debug("call byteps_declare_tensor done.")
        # import time
        # time.sleep(3)
        root_rank = 0
        if self.rank != root_rank:
            value.__imul__(0)
        logger.debug("call byteps_push_pull.")
        self.handle.byteps_push_pull(value, version=0, priority=priority,
                                name=str(key), is_average=False)
        value.wait_to_read()
        
        logger.debug("call byteps_push_pull done.")
        # Make sure tensors pushed to MXNet engine get processed such that all
        # workers are synced before starting training.

        out = out if isinstance(out, list) else [out]
        for o in out:
            value.copyto(o)

    def pushpull(self, key, value, out=None, priority=0):
        """ Performs push and pull a single value from the store.
        This function is coalesced form of push and pull operations.
        `value` is pushed to the kvstore server for the specified keys and the aggregated
        values are pulled from the server to `out`. If `out` is not specified the pulled
        values are written to `value`.
        Parameters
        ----------
        key : str, or int
            The key.
        value : NDArray, or list of NDArray
            Values corresponding to the key.
        out: NDArray, or list of NDArray
            Values corresponding to the key.
        priority : int, optional
            The priority of the operation.
            Higher priority operations are likely to be executed before other actions.
        Examples
        --------
        >>> # pushpull a single key-value pair
        >>> kv.pushpull('3', mx.nd.ones(shape)*8, out=a)
        >>> print a.asnumpy()
        [[ 8.  8.  8.]
        [ 8.  8.  8.]]
        >>> # pushpull a list of keys.
        >>> # single device
        >>> keys = ['4', '5', '6']
        >>> b = [mx.nd.zeros(shape)]*len(keys)
        >>> kv.pushpull(keys, [mx.nd.ones(shape)]*len(keys), out=b)
        >>> print b[1].asnumpy()
        [[ 1.  1.  1.]
        [ 1.  1.  1.]]
        """
        # the most common operation operates on one NDArray as `value`, and
        # `out` is set to None, for inplace pushpull.
        # unpack the list if it contains just one NDArray
        value = value[0] if isinstance(value, list) and len(value) == 1 else value
        if isinstance(value, list):
            ctx = value[0].context
            reduced_value = sum([v.as_in_context(ctx) for v in value])
        else:
            assert isinstance(value, NDArray)
            reduced_value = value
        
        self.handle.byteps_push_pull(reduced_value, version=0, priority=priority,
                                name=str(key), is_average=False)
        if out is not None:
            out = out if isinstance(out, list) else [out]
            for o in out:
                reduced_value.copyto(o)

    @staticmethod
    def is_capable(capability):
        """Queries if the KVStore type supports certain capability, such as optimizer algorithm,
        gradient compression, sparsity, etc.
        Parameters
        ----------
        capability: str
            The capability to query
        Returns
        -------
        result : bool
            Whether the capability is supported or not.
        """
        if capability == KVStoreBase.OPTIMIZER:
            return True
        else:
            raise ValueError('Unknown capability: {}'.format(capability))

    @property		
    def type(self):		
        """ Returns the type of this kvstore.		
        
        Returns		
        -------		
        type : str		
            the string type		
        """		
        return 'byteps'		

    @property		
    def local_rank(self):		
        """ Returns the local rank of this worker on the node.		
        
        Returns		
        -------		
        rank : int		
            The local rank of this node, which is in range [0, num_workers_on_current_node())		
        """		
        return self.handle.local_rank()		

    @property		
    def rank(self):		
        """ Returns the rank of this worker node.		
        
        Returns		
        -------		
        rank : int		
            The rank of this node, which is in range [0, num_workers())		
        """		
        return self.handle.rank()		

    @property		
    def num_workers(self):		
        """Returns the number of worker nodes.		
        
        Returns		
        -------		
        size :int		
            The number of worker nodes.		
        """		
        return self.handle.size()