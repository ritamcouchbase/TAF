#from tasks.future import Future
import logging
import types

import tasks.tasks as conc
import Jython_tasks.task as jython_tasks

from couchbase_helper.documentgenerator import doc_generator
from membase.api.rest_client import RestConnection
from sdk_client import SDKSmartClient as VBucketAwareMemcached
from tasks.taskmanager import TaskManager
from BucketLib.BucketOperations import BucketHelper
from Jython_tasks.task_manager import TaskManager as jython_task_manager


"""An API for scheduling tasks that run against Couchbase Server

This module is contains the top-level API's for scheduling and executing tasks. The
API provides a way to run task do syncronously and asynchronously.
"""

log = logging.getLogger(__name__)


class ServerTasks(object):
    """
    A Task API for performing various operations synchronously or
    asynchronously on Couchbase cluster
    """

    def __init__(self, task_manager=jython_task_manager()):
        self.task_manager = TaskManager("Cluster_Thread")
        self.jython_task_manager = task_manager

    def async_create_bucket(self, server, bucket):
        """
        Asynchronously creates the default bucket

        Parameters:
          bucket_params - a dictionary containing bucket creation parameters.
        Returns:
          BucketCreateTask - Task future that is a handle to the scheduled task
        """
#         bucket_params['bucket_name'] = 'default'
        _task = conc.BucketCreateTask(server, bucket,
                                      task_manager=self.task_manager)
        self.task_manager.schedule(_task)
        return _task

    def sync_create_bucket(self, server, bucket):
        """
        Synchronously creates the default bucket

        Parameters:
          bucket_params - a dictionary containing bucket creation parameters.
        Returns:
          BucketCreateTask - Task future that is a handle to the scheduled task
        """
#         bucket_params['bucket_name'] = 'default'
        _task = conc.BucketCreateTask(server, bucket,
                                      task_manager=self.task_manager)
        self.task_manager.schedule(_task)
        return _task.get_result()

    def async_bucket_delete(self, server, bucket='default'):
        """
        Asynchronously deletes a bucket

        Parameters:
          server - The server to delete the bucket on. (TestInputServer)
          bucket - The name of the bucket to be deleted. (String)

        Returns:
          BucketDeleteTask - Task future that is a handle to the scheduled task
        """
        _task = conc.BucketDeleteTask(server, self.task_manager, bucket)
        self.task_manager.schedule(_task)
        return _task

    def async_failover(self, servers=[], failover_nodes=[], graceful=False,
                       use_hostnames=False, wait_for_pending=0):
        """Asynchronously failover a set of nodes

        Parameters:
            servers - servers used for connection. (TestInputServer)
            failover_nodes - The set of servers that will under go failover .(TestInputServer)
            graceful = True/False. True - graceful, False - hard. (Boolean)

        Returns:
            FailOverTask - A task future that is a handle to the scheduled task."""
        _task = conc.FailoverTask(servers, task_manager=self.task_manager,
                             to_failover=failover_nodes,
                             graceful=graceful, use_hostnames=use_hostnames,
                             wait_for_pending=wait_for_pending)
        self.task_manager.schedule(_task)
        return _task

    def async_init_node(self, server, disabled_consistent_view=None,
                        rebalanceIndexWaitingDisabled=None, rebalanceIndexPausingDisabled=None,
                        maxParallelIndexers=None, maxParallelReplicaIndexers=None, port=None,
                        quota_percent=None, services=None, index_quota_percent=None, gsi_type='forestdb'):
        """Asynchronously initializes a node

        The task scheduled will initialize a nodes username and password and will establish
        the nodes memory quota to be 2/3 of the available system memory.

        Parameters:
            server - The server to initialize. (TestInputServer)
            disabled_consistent_view - disable consistent view
            rebalanceIndexWaitingDisabled - index waiting during rebalance(Boolean)
            rebalanceIndexPausingDisabled - index pausing during rebalance(Boolean)
            maxParallelIndexers - max parallel indexers threads(Int)
            index_quota_percent - index quote used by GSI service (added due to sherlock)
            maxParallelReplicaIndexers - max parallel replica indexers threads(int)
            port - port to initialize cluster
            quota_percent - percent of memory to initialize
            services - can be kv, n1ql, index
            gsi_type - Indexer Storage Mode
        Returns:
            NodeInitTask - A task future that is a handle to the scheduled task."""
        _task = conc.NodeInitializeTask(server, self.task_manager, disabled_consistent_view,
                                        rebalanceIndexWaitingDisabled, rebalanceIndexPausingDisabled,
                                        maxParallelIndexers, maxParallelReplicaIndexers,
                                        port, quota_percent, services=services,
                                        index_quota_percent=index_quota_percent,
                                        gsi_type=gsi_type)

        self.task_manager.schedule(_task)
        return _task

    def async_load_gen_docs(self, cluster, bucket, generator, op_type, exp=0,
                            flag=0, persist_to=0, replicate_to=0,
                            only_store_hash=True, batch_size=1, pause_secs=1,
                            timeout_secs=5, compression=True,
                            process_concurrency=8, retries=5):
        log.info("Loading documents to {}".format(bucket.name))
        client = VBucketAwareMemcached(RestConnection(cluster.master), bucket)
        _task = jython_tasks.LoadDocumentsGeneratorsTask(
            cluster, self.jython_task_manager, bucket, client, [generator],
            op_type, exp, flag=flag, persist_to=persist_to,
            replicate_to=replicate_to, only_store_hash=only_store_hash,
            batch_size=batch_size, pause_secs=pause_secs,
            timeout_secs=timeout_secs, compression=compression,
            process_concurrency=process_concurrency, retries=retries)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def async_load_gen_docs_durable(self, cluster, bucket, generator, op_type,
                                    exp=0, flag=0, persist_to=0,
                                    replicate_to=0, only_store_hash=True,
                                    batch_size=1, pause_secs=1,
                                    timeout_secs=5, compression=True,
                                    process_concurrency=1, retries=5):

        log.info("Loading documents to {}".format(bucket.name))
        client = VBucketAwareMemcached(RestConnection(cluster.master), bucket)
        _task = jython_tasks.Durability(cluster, self.jython_task_manager, bucket, client, generator,
                                                        op_type, exp, flag=flag, persist_to=persist_to,
                                                        replicate_to=replicate_to, only_store_hash=only_store_hash,
                                                        batch_size=batch_size,
                                                        pause_secs=pause_secs, timeout_secs=timeout_secs,
                                                        compression=compression,
                                                        process_concurrency=process_concurrency, retries=retries)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def load_bucket_into_dgm(self, cluster, bucket, key, num_items,
                             active_resident_threshold, load_batch_size=20000,
                             persist_to=None, replicate_to=None):
        rest = BucketHelper(cluster.master)
        bucket_stat = rest.get_bucket_stats_for_node(bucket.name,
                                                     cluster.master)
        while bucket_stat["vb_active_resident_items_ratio"] > \
                active_resident_threshold:
            gen_load = doc_generator(key, num_items,
                                     num_items+load_batch_size,
                                     doc_type="binary")
            num_items += load_batch_size
            task = self.async_load_gen_docs(
                cluster, bucket, gen_load, "create", 0,
                persist_to=persist_to, replicate_to=replicate_to,
                batch_size=10, process_concurrency=8)
            self.jython_task_manager.get_task_result(task)
            bucket_stat = rest.get_bucket_stats_for_node(bucket.name,
                                                         cluster.master)
        return num_items

    def async_validate_docs(self, cluster, bucket, generator, opt_type, exp=0, flag=0, only_store_hash=True,
                            batch_size=1, pause_secs=1, timeout_secs=5, compression=True, process_concurrency=4):
        log.info("Validating documents")
        client = VBucketAwareMemcached(RestConnection(cluster.master), bucket)
        _task = jython_tasks.DocumentsValidatorTask(cluster, self.jython_task_manager, bucket, client, [generator],
                                                    opt_type, exp, flag=flag, only_store_hash=only_store_hash, batch_size=batch_size,
                                                    pause_secs=pause_secs, timeout_secs=timeout_secs, compression=compression,
                                                    process_concurrency=process_concurrency)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def async_rebalance(self, servers, to_add, to_remove, use_hostnames=False,
                        services=None, check_vbucket_shuffling=True):
        """Asyncronously rebalances a cluster

        Parameters:
            servers - All servers participating in the rebalance ([TestInputServers])
            to_add - All servers being added to the cluster ([TestInputServers])
            to_remove - All servers being removed from the cluster ([TestInputServers])
            use_hostnames - True if nodes should be added using hostnames (Boolean)

        Returns:
            RebalanceTask - A task future that is a handle to the scheduled task"""
        _task = jython_tasks.rebalanceTask(servers, to_add, to_remove,
                                           use_hostnames=use_hostnames,
                                           services=services,
                                           check_vbucket_shuffling=check_vbucket_shuffling)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def async_wait_for_stats(self, cluster, bucket, param, stat, comparison, value):
        """Asynchronously wait for stats

        Waits for stats to match the criteria passed by the stats variable. See
        couchbase.stats_tool.StatsCommon.build_stat_check(...) for a description of
        the stats structure and how it can be built.

        Parameters:
            servers - The servers to get stats from. Specifying multiple servers will
                cause the result from each server to be added together before
                comparing. ([TestInputServer])
            bucket - The name of the bucket (String)
            param - The stats parameter to use. (String)
            stat - The stat that we want to get the value from. (String)
            comparison - How to compare the stat result to the value specified.
            value - The value to compare to.

        Returns:
            RebalanceTask - A task future that is a handle to the scheduled task"""
        _task = jython_tasks.StatsWaitTask(cluster, bucket, param, stat, comparison, value)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def async_monitor_db_fragmentation(self, server, bucket, fragmentation,
                                       get_view_frag=False):
        """
        Asyncronously monitor db fragmentation
        Parameters:
            servers - server to check(TestInputServers)
            bucket - bucket to check
            fragmentation - fragmentation to reach
            get_view_frag - Monitor view fragmentation.
                            In case enabled when <fragmentation_value> is
                            reached this method will return (boolean)
        Returns:
            MonitorDBFragmentationTask - A task future that is a handle to the
                                         scheduled task
        """
        _task = jython_tasks.MonitorDBFragmentationTask(server, fragmentation,
                                                        bucket, get_view_frag)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def create_default_bucket(self, bucket_params, timeout=600):
        """Synchronously creates the default bucket

        Parameters:
            bucket_params - A dictionary containing a list of bucket creation parameters. (Dict)

        Returns:
            boolean - Whether or not the bucket was created."""

        _task = self.async_create_default_bucket(bucket_params)
        return _task.get_result(timeout)

    def create_sasl_bucket(self, name, password,bucket_params, timeout=None):
        """Synchronously creates a sasl bucket

        Parameters:
            bucket_params - A dictionary containing a list of bucket creation parameters. (Dict)

        Returns:
            boolean - Whether or not the bucket was created."""

        _task = self.async_create_sasl_bucket(name, password, bucket_params)
        self.task_manager.schedule(_task)
        return _task.get_result(timeout)

    def create_standard_bucket(self, name, port, bucket_params, timeout=None):
        """Synchronously creates a standard bucket
        Parameters:
            bucket_params - A dictionary containing a list of bucket creation parameters. (Dict)
        Returns:
            boolean - Whether or not the bucket was created."""
        _task = self.async_create_standard_bucket(name, port, bucket_params)
        return _task.get_result(timeout)

    def bucket_delete(self, server, bucket='default', timeout=None):
        """Synchronously deletes a bucket

        Parameters:
            server - The server to delete the bucket on. (TestInputServer)
            bucket - The name of the bucket to be deleted. (String)

        Returns:
            boolean - Whether or not the bucket was deleted."""
        _task = self.async_bucket_delete(server, bucket)
        return _task.get_result(timeout)

    def init_node(self, server, async_init_node=True, disabled_consistent_view=None, services = None, index_quota_percent = None):
        """Synchronously initializes a node

        The task scheduled will initialize a nodes username and password and will establish
        the nodes memory quota to be 2/3 of the available system memory.

        Parameters:
            server - The server to initialize. (TestInputServer)
            index_quota_percent - index quota percentage
            disabled_consistent_view - disable consistent view

        Returns:
            boolean - Whether or not the node was properly initialized."""
        _task = self.async_init_node(server, async_init_node, disabled_consistent_view, services = services, index_quota_percent= index_quota_percent)
        return _task.result()

    def rebalance(self, servers, to_add, to_remove, timeout=None, use_hostnames=False, services = None):
        """Syncronously rebalances a cluster

        Parameters:
            servers - All servers participating in the rebalance ([TestInputServers])
            to_add - All servers being added to the cluster ([TestInputServers])
            to_remove - All servers being removed from the cluster ([TestInputServers])
            use_hostnames - True if nodes should be added using their hostnames (Boolean)
            services - Services definition per Node, default is None (this is since Sherlock release)
        Returns:
            boolean - Whether or not the rebalance was successful"""
        _task = self.async_rebalance(servers, to_add, to_remove, use_hostnames, services = services)
        result = self.jython_task_manager.get_task_result(_task)
        return result

    def load_gen_docs(self, cluster, bucket, generator, op_type, exp=0,
                      flag=0, persist_to=0, replicate_to=0, only_store_hash=True,
                      batch_size=1, compression=True, process_concurrency=8, retries=5):
        _task = self.async_load_gen_docs(cluster, bucket, generator, op_type, exp, flag, persist_to=persist_to,
                                         replicate_to=replicate_to,
                                         only_store_hash=only_store_hash, batch_size=batch_size, 
                                         compression=compression, process_concurrency=process_concurrency,
                                         retries=retries)
        return self.jython_task_manager.get_task_result(_task)

    def verify_data(self, server, bucket, kv_store, timeout=None, compression=True):
        _task = self.async_verify_data(server, bucket, kv_store, compression=compression)
        return _task.result(timeout)

    def async_verify_data(self, server, bucket, kv_store, max_verify=None,
                          only_store_hash=True, batch_size=1, replica_to_read=None, timeout_sec=5, compression=True):
        if batch_size > 1:
            _task = conc.BatchedValidateDataTask(server, bucket, kv_store, max_verify, only_store_hash, batch_size, 
                                                 timeout_sec, self.task_manager, compression=compression)
        else:
            _task = conc.ValidateDataTask(server, bucket, kv_store, max_verify, only_store_hash, replica_to_read, 
                                          self.task_manager, compression=compression)
        self.task_manager.schedule(_task)
        return _task
    
    def wait_for_stats(self, cluster, bucket, param, stat, comparison, value, timeout=None):
        """Synchronously wait for stats

        Waits for stats to match the criteria passed by the stats variable. See
        couchbase.stats_tool.StatsCommon.build_stat_check(...) for a description of
        the stats structure and how it can be built.

        Parameters:
            servers - The servers to get stats from. Specifying multiple servers will
                cause the result from each server to be added together before
                comparing. ([TestInputServer])
            bucket - The name of the bucket (String)
            param - The stats parameter to use. (String)
            stat - The stat that we want to get the value from. (String)
            comparison - How to compare the stat result to the value specified.
            value - The value to compare to.

        Returns:
            boolean - Whether or not the correct stats state was seen"""
        _task = self.async_wait_for_stats(cluster, bucket, param, stat, comparison, value)
        return self.jython_task_manager.get_task_result(_task)

    def shutdown(self, force=False):
        self.task_manager.shutdown(force)
        if force:
            log.info("Cluster instance shutdown with force")

    def async_n1ql_query_verification(self, server, bucket, query, n1ql_helper=None,
                                      expected_result=None, is_explain_query=False,
                                      index_name=None, verify_results=True, retry_time=2,
                                      scan_consistency=None, scan_vector=None):
        """Asynchronously runs n1ql querya and verifies result if required

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query. (dict)
            expected_result - expected result after querying
            is_explain_query - is query explain query
            index_name - index related to query
            bucket - The name of the bucket containing items for this view. (String)
            verify_results -  Verify results after query runs successfully
            retry_time - The time in seconds to wait before retrying failed queries (int)
            n1ql_helper - n1ql helper object
            scan_consistency - consistency value for querying
            scan_vector - scan vector used for consistency
        Returns:
            N1QLQueryTask - A task future that is a handle to the scheduled task."""
        _task = jython_tasks.N1QLQueryTask(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 query = query, expected_result=expected_result,
                 verify_results = verify_results,
                 is_explain_query = is_explain_query,
                 index_name = index_name,
                 retry_time= retry_time,
                 scan_consistency = scan_consistency,
                 scan_vector = scan_vector)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def n1ql_query_verification(self, server, bucket, query, n1ql_helper = None,
                                expected_result=None, is_explain_query = False,
                                index_name = None, verify_results = True,
                                scan_consistency = None, scan_vector = None,
                                retry_time=2, timeout = 60):
        """Synchronously runs n1ql querya and verifies result if required

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query. (dict)
            expected_result - expected result after querying
            is_explain_query - is query explain query
            index_name - index related to query
            bucket - The name of the bucket containing items for this view. (String)
            verify_results -  Verify results after query runs successfully
            retry_time - The time in seconds to wait before retrying failed queries (int)
            n1ql_helper - n1ql helper object
            scan_consistency - consistency used during querying
            scan_vector - vector used during querying
            timeout - timeout for task
        Returns:
            N1QLQueryTask - A task future that is a handle to the scheduled task."""
        _task = self.async_n1ql_query_verification(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 query = query, expected_result=expected_result,
                 is_explain_query = is_explain_query,
                 index_name = index_name,
                 verify_results = verify_results,
                 retry_time= retry_time,
                 scan_consistency = scan_consistency,
                 scan_vector = scan_vector)
        return self.jython_task_manager.get_task_result(_task)

    def async_create_index(self, server, bucket, query, n1ql_helper = None,
                           index_name = None, defer_build = False, retry_time=2,
                           timeout = 240):
        """Asynchronously runs create index task

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query.
            bucket - The name of the bucket containing items for this view. (String)
            index_name - Name of the index to be created
            defer_build - build is defered
            retry_time - The time in seconds to wait before retrying failed queries (int)
            n1ql_helper - n1ql helper object
            timeout - timeout for index to come online
        Returns:
            CreateIndexTask - A task future that is a handle to the scheduled task."""
        _task = jython_tasks.CreateIndexTask(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 defer_build = defer_build,
                 index_name = index_name,
                 query = query,
                 retry_time= retry_time,
                 timeout = timeout)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def async_monitor_index(self, server, bucket, n1ql_helper = None,
                            index_name = None, retry_time=2, timeout = 240):
        """Asynchronously runs create index task

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query.
            bucket - The name of the bucket containing items for this view. (String)
            index_name - Name of the index to be created
            retry_time - The time in seconds to wait before retrying failed queries (int)
            timeout - timeout for index to come online
            n1ql_helper - n1ql helper object
        Returns:
            MonitorIndexTask - A task future that is a handle to the scheduled task."""
        _task = jython_tasks.MonitorIndexTask(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 index_name = index_name,
                 retry_time= retry_time,
                 timeout = timeout)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def async_build_index(self, server, bucket, query, n1ql_helper = None, retry_time=2):
        """Asynchronously runs create index task

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query.
            bucket - The name of the bucket containing items for this view. (String)
            retry_time - The time in seconds to wait before retrying failed queries (int)
            n1ql_helper - n1ql helper object
        Returns:
            BuildIndexTask - A task future that is a handle to the scheduled task."""
        _task = jython_tasks.BuildIndexTask(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 query = query,
                 retry_time= retry_time)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def create_index(self, server, bucket, query, n1ql_helper = None, index_name = None,
                     defer_build = False, retry_time=2, timeout= 60):
        """Asynchronously runs drop index task

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query.
            bucket - The name of the bucket containing items for this view. (String)
            index_name - Name of the index to be created
            retry_time - The time in seconds to wait before retrying failed queries (int)
            n1ql_helper - n1ql helper object
            defer_build - defer the build
            timeout - timeout for the task
        Returns:
            N1QLQueryTask - A task future that is a handle to the scheduled task."""
        _task = self.async_create_index(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 query = query,
                 index_name = index_name,
                 defer_build = defer_build,
                 retry_time= retry_time)
        return self.jython_task_manager.get_task_result(_task)

    def async_drop_index(self, server = None, bucket = "default", query = None,
                         n1ql_helper = None, index_name = None, retry_time=2):
        """Synchronously runs drop index task

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query.
            bucket - The name of the bucket containing items for this view. (String)
            index_name - Name of the index to be dropped
            retry_time - The time in seconds to wait before retrying failed queries (int)
            n1ql_helper - n1ql helper object
        Returns:
            DropIndexTask - A task future that is a handle to the scheduled task."""
        _task = jython_tasks.DropIndexTask(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 query = query,
                 index_name = index_name,
                 retry_time= retry_time)
        self.jython_task_manager.add_new_task(_task)
        return _task

    def drop_index(self, server, bucket, query, n1ql_helper = None,
                   index_name = None, retry_time=2, timeout = 60):
        """Synchronously runs drop index task

        Parameters:
            server - The server to handle query verification task. (TestInputServer)
            query - Query params being used with the query. (dict)
            bucket - The name of the bucket containing items for this view. (String)
            index_name - Name of the index to be created
            retry_time - The time in seconds to wait before retrying failed queries (int)
            n1ql_helper - n1ql helper object
            timeout - timeout for the task
        Returns:
            N1QLQueryTask - A task future that is a handle to the scheduled task."""
        _task = self.async_drop_index(n1ql_helper = n1ql_helper,
                 server = server, bucket = bucket,
                 query = query,
                 index_name = index_name,
                 retry_time= retry_time)
        return self.jython_task_manager.get_task_result(_task)

    def failover(self, servers=[], failover_nodes=[], graceful=False, use_hostnames=False,timeout=None):
        """Synchronously flushes a bucket

        Parameters:
            servers - node used for connection (TestInputServer)
            failover_nodes - servers to be failovered, i.e. removed from the cluster. (TestInputServer)
            bucket - The name of the bucket to be flushed. (String)

        Returns:
            boolean - Whether or not the bucket was flushed."""
        _task = self.async_failover(servers, failover_nodes, graceful, use_hostnames)
        return _task.result(timeout)

    def async_bucket_flush(self, server, bucket='default'):
        """Asynchronously flushes a bucket

        Parameters:
            server - The server to flush the bucket on. (TestInputServer)
            bucket - The name of the bucket to be flushed. (String)

        Returns:
            BucketFlushTask - A task future that is a handle to the scheduled task."""
        _task = conc.BucketFlushTask(server,self.task_manager,bucket)
        self.task_manager.schedule(_task)
        return _task

    def bucket_flush(self, server, bucket='default', timeout=None):
        """Synchronously flushes a bucket

        Parameters:
            server - The server to flush the bucket on. (TestInputServer)
            bucket - The name of the bucket to be flushed. (String)

        Returns:
            boolean - Whether or not the bucket was flushed."""
        _task = self.async_bucket_flush(server, bucket)
        return _task.get_result(timeout)

    def async_compact_bucket(self, server, bucket="default"):
        """Asynchronously starts bucket compaction

        Parameters:
            server - source couchbase server
            bucket - bucket to compact

        Returns:
            boolean - Whether or not the compaction started successfully"""
        _task = conc.CompactBucketTask(server, self.task_manager, bucket)
        self.task_manager.schedule(_task)
        return _task

    def compact_bucket(self, server, bucket="default"):
        """Synchronously runs bucket compaction and monitors progress

        Parameters:
            server - source couchbase server
            bucket - bucket to compact

        Returns:
            boolean - Whether or not the cbrecovery completed successfully"""
        _task = self.async_compact_bucket(server, bucket)
        status = _task.get_result()
        return status

    def async_cbas_query_execute(self, master, cbas_server, cbas_endpoint, statement, bucket='default', mode=None, pretty=True):
        """
        Asynchronously execute a CBAS query
        :param master: Master server
        :param cbas_server: CBAS server
        :param cbas_endpoint: CBAS Endpoint URL (/analytics/service)
        :param statement: Query to be executed
        :param bucket: bucket to connect
        :param mode: Query Execution mode
        :param pretty: Pretty formatting
        :return: task with the output or error message
        """
        _task = conc.CBASQueryExecuteTask(master, cbas_server, self.task_manager, cbas_endpoint, statement, bucket,
                                          mode, pretty)
        self.task_manager.schedule(_task)
        return _task
