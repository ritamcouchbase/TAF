'''
Created on Sep 26, 2017

@author: riteshagarwal
'''
import copy
import types

from Jython_tasks.task import PrintClusterStats, MonitorActiveTask
from couchbase_cli import CouchbaseCLI
from membase.api.rest_client import RestConnection, RestHelper
from remote.remote_util import RemoteMachineShellConnection, RemoteUtilHelper
from membase.helper.cluster_helper import ClusterOperationHelper
from TestInput import TestInputSingleton
import testconstants
import logger
import time


class CBCluster:
    
    def __init__(self, name="default",username="Administrator", 
                 password="password", paths=None, servers=None):
        self.name = name
        self.username = username
        self.password = password
        self.paths = paths
        self.ram_settings = {}
        self.servers = servers
        self.nodes_in_cluster = []
        self.master = servers[0]
    
    def update_master(self,master):
        self.master = master

class cluster_utils():
    
    def __init__(self, cluster, task_manager):
        self.input = TestInputSingleton.input
        self.cluster = cluster
        self.task_manager = task_manager
        self.rest = RestConnection(cluster.master)
        self.vbuckets = self.input.param("vbuckets", 1024)
        self.upr = self.input.param("upr", None)
        self.log = logger.Logger.get_logger()
    
    def cluster_cleanup(self, bucket_util):
        rest = RestConnection(self.cluster.master)
        if rest._rebalance_progress_status() == 'running':
            self.kill_memcached()
            self.log.warning("rebalancing is still running, test should be verified")
            stopped = rest.stop_rebalance()
            if not stopped:
                raise Exception("Unable to stop rebalance")
        bucket_util.delete_all_buckets(self.cluster.servers)
        self.cleanup_cluster(self.cluster.servers, master=self.cluster.master)
        self.wait_for_ns_servers_or_assert(self.cluster.servers)

    #wait_if_warmup=True is useful in tearDown method for (auto)failover tests
    def wait_for_ns_servers_or_assert(self, servers, wait_time=360, wait_if_warmup=False):
        for server in servers:
            rest = RestConnection(server)
            log = logger.Logger.get_logger()
            log.info("waiting for ns_server @ {0}:{1}".format(server.ip, server.port))
            if RestHelper(rest).is_ns_server_running(wait_time):
                log.info("ns_server @ {0}:{1} is running".format(server.ip, server.port))
            else:
                log.info("ns_server {0} is not running in {1} sec".format(server.ip, wait_time))
                return False
            return True

    def cleanup_cluster(self, wait_for_rebalance=True, master=None):
        log = logger.Logger.get_logger()
        if master is None:
            master = self.cluster.master
        rest = RestConnection(master)
        helper = RestHelper(rest)
        helper.is_ns_server_running(timeout_in_seconds=testconstants.NS_SERVER_TIMEOUT)
        nodes = rest.node_statuses()
        master_id = rest.get_nodes_self().id
        for node in nodes:
            if int(node.port) in xrange(9091, 9991):
                rest.eject_node(node)
                nodes.remove(node)

        if len(nodes) > 1:
            log.info("rebalancing all nodes in order to remove nodes")
            rest.log_client_error("Starting rebalance from test, ejected nodes %s" % \
                                                             [node.id for node in nodes if node.id != master_id])
            removed = helper.remove_nodes(knownNodes=[node.id for node in nodes],
                                          ejectedNodes=[node.id for node in nodes if node.id != master_id],
                                          wait_for_rebalance=wait_for_rebalance)
            success_cleaned = []
            for removed in [node for node in nodes if (node.id != master_id)]:
                removed.rest_password = self.cluster.master.rest_password
                removed.rest_username = self.cluster.master.rest_username
                try:
                    rest = RestConnection(removed)
                except Exception as ex:
                    log.error("can't create rest connection after rebalance out for ejected nodes,\
                        will retry after 10 seconds according to MB-8430: {0} ".format(ex))
                    time.sleep(10)
                    rest = RestConnection(removed)
                start = time.time()
                while time.time() - start < 30:
                    if len(rest.get_pools_info()["pools"]) == 0:
                        success_cleaned.append(removed)
                        break
                    else:
                        time.sleep(0.1)
                if time.time() - start > 10:
                    log.error("'pools' on node {0}:{1} - {2}".format(
                           removed.ip, removed.port, rest.get_pools_info()["pools"]))
            for node in set([node for node in nodes if (node.id != master_id)]) - set(success_cleaned):
                log.error("node {0}:{1} was not cleaned after removing from cluster".format(
                           removed.ip, removed.port))
                try:
                    rest = RestConnection(node)
                    rest.force_eject_node()
                except Exception as ex:
                    log.error("force_eject_node {0}:{1} failed: {2}".format(removed.ip, removed.port, ex))
            if len(set([node for node in nodes if (node.id != master_id)])\
                    - set(success_cleaned)) != 0:
                raise Exception("not all ejected nodes were cleaned successfully")

            log.info("removed all the nodes from cluster associated with {0} ? {1}".format(self.cluster.master, \
                    [(node.id, node.port) for node in nodes if (node.id != master_id)]))
            
    def get_nodes_in_cluster(self, master_node=None):
        rest = None
        if master_node == None:
            rest = RestConnection(self.cluster.master)
        else:
            rest = RestConnection(master_node)
        nodes = rest.node_statuses()
        server_set = []
        for node in nodes:
            for server in self.cluster.servers:
                if server.ip == node.ip:
                    server_set.append(server)
        return server_set

    def change_checkpoint_params(self):
        self.chk_max_items = self.input.param("chk_max_items", None)
        self.chk_period = self.input.param("chk_period", None)
        if self.chk_max_items or self.chk_period:
            for server in self.cluster.servers:
                rest = RestConnection(server)
                if self.chk_max_items:
                    rest.set_chk_max_items(self.chk_max_items)
                if self.chk_period:
                    rest.set_chk_period(self.chk_period)

    def change_password(self, new_password="new_password"):
        nodes = RestConnection(self.cluster.master).node_statuses()


        cli = CouchbaseCLI(self.cluster.master, self.cluster.master.rest_username, self.cluster.master.rest_password  )
        output, err, result = cli.setting_cluster(data_ramsize=False, index_ramsize=False, fts_ramsize=False, cluster_name=None,
                         cluster_username=None, cluster_password=new_password, cluster_port=False)

        self.log.info(output)
        # MB-10136 & MB-9991
        if not result:
            raise Exception("Password didn't change!")
        self.log.info("new password '%s' on nodes: %s" % (new_password, [node.ip for node in nodes]))
        for node in nodes:
            for server in self.cluster.servers:
                if server.ip == node.ip and int(server.port) == int(node.port):
                    server.rest_password = new_password
                    break

    def change_port(self, new_port="9090", current_port='8091'):
        nodes = RestConnection(self.cluster.master).node_statuses()
        remote_client = RemoteMachineShellConnection(self.cluster.master)
        options = "--cluster-port=%s" % new_port
        cli_command = "cluster-edit"
        output, error = remote_client.execute_couchbase_cli(cli_command=cli_command, options=options,
                                                            cluster_host="localhost:%s" % current_port,
                                                            user=self.cluster.master.rest_username,
                                                            password=self.cluster.master.rest_password)
        self.log.info(output)
        # MB-10136 & MB-9991
        if error:
            raise Exception("Port didn't change! %s" % error)
        self.port = new_port
        self.log.info("new port '%s' on nodes: %s" % (new_port, [node.ip for node in nodes]))
        for node in nodes:
            for server in self.cluster.servers:
                if server.ip == node.ip and int(server.port) == int(node.port):
                    server.port = new_port
                    break

    def change_env_variables(self):
        if self.vbuckets != 1024 or self.upr != None:
            for server in self.cluster.servers:
                dict = {}
                if self.vbuckets:
                    dict["COUCHBASE_NUM_VBUCKETS"] = self.vbuckets
                if self.upr != None:
                    if self.upr:
                        dict["COUCHBASE_REPL_TYPE"] = "upr"
                    else:
                        dict["COUCHBASE_REPL_TYPE"] = "tap"
                if len(dict) >= 1:
                    remote_client = RemoteMachineShellConnection(server)
                    remote_client.change_env_variables(dict)
                    remote_client.disconnect()
            self.log.info("========= CHANGED ENVIRONMENT SETTING ===========")

    def reset_env_variables(self):
        if self.vbuckets != 1024 or self.upr != None:
            for server in self.cluster.servers:
                if self.upr or self.vbuckets:
                    remote_client = RemoteMachineShellConnection(server)
                    remote_client.reset_env_variables()
                    remote_client.disconnect()
            self.log.info("========= RESET ENVIRONMENT SETTING TO ORIGINAL ===========")

    def change_log_info(self):
        for server in self.cluster.servers:
            remote_client = RemoteMachineShellConnection(server)
            remote_client.stop_couchbase()
            remote_client.change_log_level(self.log_info)
            remote_client.start_couchbase()
            remote_client.disconnect()
        self.log.info("========= CHANGED LOG LEVELS ===========")

    def change_log_location(self):
        for server in self.cluster.servers:
            remote_client = RemoteMachineShellConnection(server)
            remote_client.stop_couchbase()
            remote_client.configure_log_location(self.log_location)
            remote_client.start_couchbase()
            remote_client.disconnect()
        self.log.info("========= CHANGED LOG LOCATION ===========")

    def change_stat_info(self):
        for server in self.cluster.servers:
            remote_client = RemoteMachineShellConnection(server)
            remote_client.stop_couchbase()
            remote_client.change_stat_periodicity(self.stat_info)
            remote_client.start_couchbase()
            remote_client.disconnect()
        self.log.info("========= CHANGED STAT PERIODICITY ===========")

    def change_port_info(self):
        for server in self.cluster.servers:
            remote_client = RemoteMachineShellConnection(server)
            remote_client.stop_couchbase()
            remote_client.change_port_static(self.port_info)
            server.port = self.port_info
            self.log.info("New REST port %s" % server.port)
            remote_client.start_couchbase()
            remote_client.disconnect()
        self.log.info("========= CHANGED ALL PORTS ===========")

    def force_eject_nodes(self):
        for server in self.cluster.servers:
            if server != self.cluster.servers[0]:
                try:
                    rest = RestConnection(server)
                    rest.force_eject_node()
                except BaseException, e:
                    self.log.error(e)

    def set_upr_flow_control(self, flow=True, servers=[]):
        servers = self.get_kv_nodes(servers)
        for bucket in self.buckets:
            for server in servers:
                rest = RestConnection(server)
                rest.set_enable_flow_control(bucket=bucket.name, flow=flow)
        for server in self.cluster.servers:
            remote_client = RemoteMachineShellConnection(server)
            remote_client.stop_couchbase()
            remote_client.start_couchbase()
            remote_client.disconnect()

    def kill_memcached(self):
        for server in self.cluster.servers:
            remote_client = RemoteMachineShellConnection(server)
            remote_client.kill_memcached()
            remote_client.disconnect()
            
    def get_nodes(self, server):
        """ Get Nodes from list of server """
        rest = RestConnection(self.cluster.master)
        nodes = rest.get_nodes()
        return nodes
    
    def stop_server(self, node):
        """ Method to stop a server which is subject to failover """
        for server in self.cluster.servers:
            if server.ip == node.ip:
                shell = RemoteMachineShellConnection(server)
                if shell.is_couchbase_installed():
                    shell.stop_couchbase()
                    self.log.info("Couchbase stopped")
                else:
                    shell.stop_membase()
                    self.log.info("Membase stopped")
                shell.disconnect()
                break

    def start_server(self, node):
        """ Method to start a server which is subject to failover """
        for server in self.cluster.servers:
            if server.ip == node.ip:
                shell = RemoteMachineShellConnection(server)
                if shell.is_couchbase_installed():
                    shell.start_couchbase()
                    self.log.info("Couchbase started")
                else:
                    shell.start_membase()
                    self.log.info("Membase started")
                shell.disconnect()
                break

    def kill_server_memcached(self, node):
        """ Method to start a server which is subject to failover """
        for server in self.cluster.servers:
            if server.ip == node.ip:
                remote_client = RemoteMachineShellConnection(server)
                remote_client.kill_memcached()
                remote_client.disconnect()

    def start_firewall_on_node(self, node):
        """ Method to start a server which is subject to failover """
        for server in self.cluster.servers:
            if server.ip == node.ip:
                RemoteUtilHelper.enable_firewall(server)

    def stop_firewall_on_node(self, node):
        """ Method to start a server which is subject to failover """
        for server in self.cluster.servers:
            if server.ip == node.ip:
                remote_client = RemoteMachineShellConnection(server)
                remote_client.disable_firewall()
                remote_client.disconnect()
            
    def reset_cluster(self):
        try:
            for node in self.cluster.servers:
                shell = RemoteMachineShellConnection(node)
                # Start node
                rest = RestConnection(node)
                data_path = rest.get_data_path()
                # Stop node
                self.stop_server(node)
                # Delete Path
                shell.cleanup_data_config(data_path)
                self.start_server(node)
            time.sleep(10)
        except Exception, ex:
            self.log.info(ex)

    def get_nodes_from_services_map(self, service_type="n1ql", get_all_nodes=False, servers=None, master=None):
        if not servers:
            servers = self.cluster.servers
        if not master:
            master = self.cluster.master
        services_map = self.get_services_map(master=master)
        if (service_type not in services_map):
            self.log.info("cannot find service node {0} in cluster " \
                          .format(service_type))
        else:
            list = []
            for server_info in services_map[service_type]:
                tokens = server_info.split(":")
                ip = tokens[0]
                port = int(tokens[1])
                for server in servers:
                    """ In tests use hostname, if IP in ini file use IP, we need
                        to convert it to hostname to compare it with hostname
                        in cluster """
                    if "couchbase.com" in ip and "couchbase.com" not in server.ip:
                        shell = RemoteMachineShellConnection(server)
                        hostname = shell.get_full_hostname()
                        self.log.info("convert IP: {0} to hostname: {1}" \
                                      .format(server.ip, hostname))
                        server.ip = hostname
                        shell.disconnect()
                    if (port != 8091 and port == int(server.port)) or \
                            (port == 8091 and server.ip == ip):
                        list.append(server)
            self.log.info("list of all nodes in cluster: {0}".format(list))
            if get_all_nodes:
                return list
            else:
                return list[0]

    def get_services_map(self, reset=True, master=None):
        if not reset:
            return
        else:
            services_map = {}
        if not master:
            master = self.cluster.master
        rest = RestConnection(master)
        map = rest.get_nodes_services()
        for key, val in map.iteritems():
            for service in val:
                if service not in services_map.keys():
                    services_map[service] = []
                services_map[service].append(key)
        return services_map

    def get_services(self, tgt_nodes, tgt_services, start_node=1):
        services = []
        if tgt_services == None:
            for node in tgt_nodes[start_node:]:
                if node.services != None and node.services != '':
                    services.append(node.services)
            if len(services) > 0:
                return services
            else:
                return None
        if tgt_services != None and "-" in tgt_services:
            services = tgt_services.replace(":", ",").split("-")[start_node:]
        elif tgt_services != None:
            for node in range(start_node, len(tgt_nodes)):
                services.append(tgt_services.replace(":", ","))
        return services

    def generate_map_nodes_out_dist(self, nodes_out_dist=None, targetMaster=False, targetIndexManager=False):
        if nodes_out_dist is None:
            nodes_out_dist = []
        index_nodes_out = []
        nodes_out_list = []
        services_map = self.get_services_map(reset=True)
        if not nodes_out_dist:
            if len(self.cluster.servers) > 1:
                nodes_out_list.append(self.cluster.servers[1])
            return nodes_out_list, index_nodes_out
        for service_fail_map in nodes_out_dist.split("-"):
            tokens = service_fail_map.rsplit(":", 1)
            count = 0
            service_type = tokens[0]
            service_type_count = int(tokens[1])
            compare_string_master = "{0}:{1}".format(self.cluster.master.ip, self.cluster.master.port)
            compare_string_index_manager = "{0}:{1}".format(self.cluster.master.ip, self.cluster.master.port)
            if service_type in services_map.keys():
                for node_info in services_map[service_type]:
                    for server in self.cluster.servers:
                        compare_string_server = "{0}:{1}".format(server.ip, server.port)
                        addNode = False
                        if (targetMaster and (not targetIndexManager)) \
                                and (
                                                compare_string_server == node_info and compare_string_master == compare_string_server):
                            addNode = True
                            self.master = self.cluster.servers[1]
                        elif ((not targetMaster) and (not targetIndexManager)) \
                                and (
                                                    compare_string_server == node_info and compare_string_master != compare_string_server \
                                                and compare_string_index_manager != compare_string_server):
                            addNode = True
                        elif ((not targetMaster) and targetIndexManager) \
                                and (
                                                    compare_string_server == node_info and compare_string_master != compare_string_server
                                        and compare_string_index_manager == compare_string_server):
                            addNode = True
                        if addNode and (server not in nodes_out_list) and count < service_type_count:
                            count += 1
                            if service_type == "index":
                                if server not in index_nodes_out:
                                    index_nodes_out.append(server)
                            nodes_out_list.append(server)
        return nodes_out_list, index_nodes_out

    def setDebugLevel(self, index_servers=None, service_type="kv"):
        index_debug_level = self.input.param("index_debug_level", None)
        if index_debug_level == None:
            return
        if index_servers == None:
            index_servers = self.get_nodes_from_services_map(service_type=service_type, get_all_nodes=True)
        json = {
            "indexer.settings.log_level": "debug",
            "projector.settings.log_level": "debug",
        }
        for server in index_servers:
            RestConnection(server).set_index_settings(json)

    def _version_compatability(self, compatible_version):
        rest = RestConnection(self.cluster.master)
        versions = rest.get_nodes_versions()
        for version in versions:
            if compatible_version <= version:
                return True
        return False

    def get_kv_nodes(self, servers=None, master=None):
        if not master:
            master = self.cluster.master
        rest = RestConnection(master)
        versions = rest.get_nodes_versions()
        for version in versions: 
            if "3.5" > version:
                return servers
        if servers == None:
            servers = self.cluster.servers
        kv_servers = self.get_nodes_from_services_map(service_type="kv", get_all_nodes=True,servers=servers, master=master)
        new_servers = []
        for server in servers:
            for kv_server in kv_servers:
                if kv_server.ip == server.ip and kv_server.port == server.port and (server not in new_servers):
                    new_servers.append(server)
        return new_servers

    def get_protocol_type(self):
        rest = RestConnection(self.cluster.master)
        versions = rest.get_nodes_versions()
        for version in versions:
            if "3" > version:
                return "tap"
        return "dcp"

    def generate_services_map(self, nodes, services=None):
        map = {}
        index = 0
        if services == None:
            return map
        for node in nodes:
            map[node.ip] = node.services
            index += 1
        return map

    def find_node_info(self, master, node):
        """ Get Nodes from list of server """
        target_node = None
        rest = RestConnection(master)
        nodes = rest.get_nodes()
        for server in nodes:
            if server.ip == node.ip:
                target_node = server
        return target_node

    def add_remove_servers(self, servers=[], list=[], remove_list=[], add_list=[]):
        """ Add or Remove servers from server list """
        initial_list = copy.deepcopy(list)
        for add_server in add_list:
            for server in self.cluster.servers:
                if add_server != None and server.ip == add_server.ip:
                    initial_list.append(add_server)
        for remove_server in remove_list:
            for server in initial_list:
                if remove_server != None and server.ip == remove_server.ip:
                    initial_list.remove(server)
        return initial_list

    def add_all_nodes_then_rebalance(self, nodes, wait_for_completion=True):
        otpNodes = []
        if len(nodes)>=1:
            for server in nodes:
                '''This is the case when master node is running cbas service as well'''
                if self.cluster.master.ip != server.ip:
                    otpNodes.append(self.rest.add_node(user=server.rest_username,
                                               password=server.rest_password,
                                               remoteIp=server.ip,
                                               port=8091,
                                               services=server.services.split(",")))
    
            self.rebalance(wait_for_completion)
        else:
            self.log.info("No Nodes provided to add in cluster")

        return otpNodes
    
    def rebalance(self, wait_for_completion=True, ejected_nodes = []):
        nodes = self.rest.node_statuses()
        started = self.rest.rebalance(otpNodes=[node.id for node in nodes],ejectedNodes=ejected_nodes)
        if started and wait_for_completion:
            result = self.rest.monitorRebalance()
#             self.assertTrue(result, "Rebalance operation failed after adding %s cbas nodes,"%self.cbas_servers)
            self.log.info("successfully rebalanced cluster {0}".format(result))
        else:
            result = started
        return result
#             self.assertTrue(started, "Rebalance operation started and in progress %s,"%self.cbas_servers)
        
    def remove_all_nodes_then_rebalance(self,otpnodes=None, rebalance=True ):
        return self.remove_node(otpnodes,rebalance) 
        
    def add_node(self, node=None, services=None, rebalance=True, wait_for_rebalance_completion=True):
        if not node:
            self.fail("There is no node to add to cluster.")
        if not services:
            services = node.services.split(",")        
        otpnode = self.rest.add_node(user=node.rest_username,
                               password=node.rest_password,
                               remoteIp=node.ip,
                               port=8091,
                               services=services
                               )
        if rebalance:
            self.rebalance(wait_for_completion=wait_for_rebalance_completion)
        return otpnode
    
    def remove_node(self,otpnode=None, wait_for_rebalance=True):
        nodes = self.rest.node_statuses()
        '''This is the case when master node is running cbas service as well'''
        if len(nodes) <= len(otpnode):
            return
        
        helper = RestHelper(self.rest)
        try:
            removed = helper.remove_nodes(knownNodes=[node.id for node in nodes],
                                              ejectedNodes=[node.id for node in otpnode],
                                              wait_for_rebalance=wait_for_rebalance)
        except Exception as e:
            self.log.info("First time rebalance failed on Removal. Wait and try again. THIS IS A BUG.")
            time.sleep(5)
            removed = helper.remove_nodes(knownNodes=[node.id for node in nodes],
                                              ejectedNodes=[node.id for node in otpnode],
                                              wait_for_rebalance=wait_for_rebalance)
        if wait_for_rebalance:
            removed
#             self.assertTrue(removed, "Rebalance operation failed while removing %s,"%otpnode)

    def get_victim_nodes(self, nodes, master=None, chosen=None, victim_type="master", victim_count=1):
        victim_nodes = [master]
        if victim_type == "graceful_failover_node":
            victim_nodes = [chosen]
        elif victim_type == "other":
            victim_nodes = self.add_remove_servers(nodes, nodes, [chosen, self.cluster.master], [])
            victim_nodes = victim_nodes[:victim_count]
        return victim_nodes

    def print_cluster_stats(self):
        rest = RestConnection(self.cluster.master)
        cluster_stat = rest.get_cluster_stats()
        self.log.info("------- Cluster statistics -------")
        for cluster_node, node_stats in cluster_stat.items():
            self.log.info("{0} => {1}".format(cluster_node, node_stats))
        self.log.info("--- End of cluster statistics ---")

    def async_print_cluster_stats(self, sleep=300):
        _task = PrintClusterStats(self.cluster.master,sleep)
        self.task_manager.add_new_task(_task)
        return _task

    def verify_replica_distribution_in_zones(self, nodes):
        """
        Verify the replica distribution in nodes in different zones.
        Validate that no replicas of a node are in the same zone.
        :param nodes: Map of the nodes in different zones. Each key contains the zone name and the ip of nodes in that zone.
        """
        shell = RemoteMachineShellConnection(self.cluster.master)
        info = shell.extract_remote_info().type.lower()
        if info == 'linux':
            cbstat_command = "{0:s}cbstats".format(testconstants.LINUX_COUCHBASE_BIN_PATH)
        elif info == 'windows':
            cbstat_command = "{0:s}cbstats".format(testconstants.WIN_COUCHBASE_BIN_PATH)
        elif info == 'mac':
            cbstat_command = "{0:s}cbstats".format(testconstants.MAC_COUCHBASE_BIN_PATH)
        else:
            raise Exception("OS not supported.")
        saslpassword = ''
        versions = RestConnection(self.cluster.master).get_nodes_versions()
        for group in nodes:
            for node in nodes[group]:
                if versions[0][:5] in testconstants.COUCHBASE_VERSION_2:
                    command = "tap"
                    if not info == 'windows':
                        commands = "%s %s:11210 %s -b %s -p \"%s\" | grep :vb_filter: |  awk '{print $1}' \
                            | xargs | sed 's/eq_tapq:replication_ns_1@//g'  | sed 's/:vb_filter://g' \
                            " % (cbstat_command, node, command, "default", saslpassword)
                    else:
                        commands = "%s %s:11210 %s -b %s -p \"%s\" | grep.exe :vb_filter: | gawk.exe '{print $1}' \
                               | sed.exe 's/eq_tapq:replication_ns_1@//g'  | sed.exe 's/:vb_filter://g' \
                               " % (cbstat_command, node, command, "default", saslpassword)
                    output, error = shell.execute_command(commands)
                elif versions[0][:5] in testconstants.COUCHBASE_VERSION_3 or \
                                versions[0][:5] in testconstants.COUCHBASE_FROM_VERSION_4:
                    command = "dcp"
                    if not info == 'windows':
                        commands = "%s %s:11210 %s -b %s -p \"%s\" | grep :replication:ns_1@%s |  grep vb_uuid | \
                                    awk '{print $1}' | sed 's/eq_dcpq:replication:ns_1@%s->ns_1@//g' | \
                                    sed 's/:.*//g' | sort -u | xargs \
                                   " % (cbstat_command, node, command, "default", saslpassword, node, node)
                        output, error = shell.execute_command(commands)
                    else:
                        commands = "%s %s:11210 %s -b %s -p \"%s\" | grep.exe :replication:ns_1@%s |  grep vb_uuid | \
                                    gawk.exe '{print $1}' | sed.exe 's/eq_dcpq:replication:ns_1@%s->ns_1@//g' | \
                                    sed.exe 's/:.*//g' \
                                   " % (cbstat_command, node, command, "default", saslpassword, node, node)
                        output, error = shell.execute_command(commands)
                        output = sorted(set(output))
                shell.log_command_output(output, error)
                output = output[0].split(" ")
                if node not in output:
                    self.log.info("{0}".format(nodes))
                    self.log.info("replicas of node {0} are in nodes {1}".format(node, output))
                    self.log.info("replicas of node {0} are not in its zone {1}".format(node, group))
                else:
                    raise Exception("replica of node {0} are on its own zone {1}".format(node, group))
        shell.disconnect()

    def modify_fragmentation_config(self, config, bucket="default"):
        rest = RestConnection(self.cluster.master)
        _config = {"parallelDBAndVC": "false",
                       "dbFragmentThreshold": None,
                       "viewFragmntThreshold": None,
                       "dbFragmentThresholdPercentage": 100,
                       "viewFragmntThresholdPercentage": 100,
                       "allowedTimePeriodFromHour": None,
                       "allowedTimePeriodFromMin": None,
                       "allowedTimePeriodToHour": None,
                       "allowedTimePeriodToMin": None,
                       "allowedTimePeriodAbort": None,
                       "autoCompactionDefined": "true"}
        for key in config:
            _config[key] = config[key]
        
        rest.set_auto_compaction(parallelDBAndVC=_config["parallelDBAndVC"],
                                     dbFragmentThreshold=_config["dbFragmentThreshold"],
                                     viewFragmntThreshold=_config["viewFragmntThreshold"],
                                     dbFragmentThresholdPercentage=_config["dbFragmentThresholdPercentage"],
                                     viewFragmntThresholdPercentage=_config["viewFragmntThresholdPercentage"],
                                     allowedTimePeriodFromHour=_config["allowedTimePeriodFromHour"],
                                     allowedTimePeriodFromMin=_config["allowedTimePeriodFromMin"],
                                     allowedTimePeriodToHour=_config["allowedTimePeriodToHour"],
                                     allowedTimePeriodToMin=_config["allowedTimePeriodToMin"],
                                     allowedTimePeriodAbort=_config["allowedTimePeriodAbort"],
                                     bucket=bucket)
        time.sleep(5)

    def async_monitor_active_task(self, servers,
                                  type_task,
                                  target_value,
                                  wait_progress=100,
                                  num_iteration=100,
                                  wait_task=True):
        """Asynchronously monitor active task.

           When active task reached wait_progress this method  will return.

        Parameters:
            servers - list of servers or The server to handle fragmentation config task. (TestInputServer)
            type_task - task type('indexer' , 'bucket_compaction', 'view_compaction' ) (String)
            target_value - target value (for example "_design/ddoc" for indexing, bucket "default"
                for bucket_compaction or "_design/dev_view" for view_compaction) (String)
            wait_progress - expected progress (int)
            num_iteration - failed test if progress is not changed during num iterations(int)
            wait_task - expect to find task in the first attempt(bool)

        Returns:
            list of MonitorActiveTask - A task future that is a handle to the scheduled task."""
        _tasks = []
        if type(servers) != types.ListType:
            servers = [servers, ]
        for server in servers:
            _task = MonitorActiveTask(server, type_task, target_value, wait_progress, num_iteration, wait_task)
            self.task_manager.add_new_task(_task)
            _tasks.append(_task)
        return _tasks