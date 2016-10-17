__author__ = 'rakesh.varma'
from node_operations import *
from config_operations import *
from aws_ec2_operations import *
import time
import random
from fabric_helper import *

c = ConfigOps()

@task
def create_aws_hadoop_cluster():
    local('python hadoop_cluster.py')

@task
def update_config():
    ec2 = aws_ec2_operations(
        region=c.aws_region,
        access_key_id=c.aws_access_key_id,
        secret_access_key=c.aws_secret_access_key
    )
    ec2.update_tags(c.all_nodes)


@task
def test_config():
    hadoop_cluster = HadoopCluster()
    print hadoop_cluster.getNode(c.hadoop_namenode).ip_address


@task
def install_salt():
    hadoop_cluster = HadoopCluster()
    time.sleep(20)

    #Install Salt Master
    fb = fabric_helper(
        host_ip  = hadoop_cluster.getNode(c.saltmaster).ip_address,
        host_user = c.aws_user,
        host_key_file = c.aws_key_location
    )
    fb.install_salt_master()
    time.sleep(5)
    #Install Salt Minions
    hosts = c.all_hadoop_nodes
    for host in hosts:
        fb = fabric_helper(
            host_ip  = hadoop_cluster.getNode(host).ip_address,
            host_user = c.aws_user,
            host_key_file = c.aws_key_location
        )
        fb.install_salt_minion(master = hadoop_cluster.getNode(c.saltmaster).private_ip_address, minion = host)
    time.sleep(5)
    #Accept Salt minions keys in Salt Master.
    fb = fabric_helper(
        host_ip  = hadoop_cluster.getNode(c.saltmaster).ip_address,
        host_user = c.aws_user,
        host_key_file = c.aws_key_location
    )
    fb.salt_master_keys_accept()
    fb.run_salt_master_ping()
    time.sleep(5)

@task
def setup_hadoop_nodes_access():
    hadoop_cluster = HadoopCluster()
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    hosts = c.all_hadoop_nodes
    for host in hosts:
        env.host_string = hadoop_cluster.getNode(host).ip_address
        #Changing the host name of hadoop nodes to EC2 public dns name.
        cmd_change_hostname = 'hostname {0}'.format(hadoop_cluster.getNode(host).dns_name)
        sudo(cmd_change_hostname)
        #Changing /etc/hosts file to remove localhost and replacing it with the public dns name and 127.0.0.1 with localip.
        sudo('sed -i -e "s/localhost/{0}/" /etc/hosts'.format(hadoop_cluster.getNode(host).dns_name))
        sudo('sed -i -e "s/127.0.0.1/{0}/" /etc/hosts'.format(hadoop_cluster.getNode(host).private_ip_address))


    # Setting up passwordless login from hadoopnamenode to all other hadoop nodes.
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    #generating ssh keys in id_rsa, no passphrase.
    run('ssh-keygen -t rsa -f /home/ubuntu/.ssh/id_rsa -q -N ""')
    #adding StrictHostKeyChecking no in the .ssh/config file so that ssh login is not prompted.
    run('echo "{0}" > /home/ubuntu/.ssh/config'.format("Host *"))
    run('echo "{0}" >> /home/ubuntu/.ssh/config'.format("   StrictHostKeyChecking no"))
    #Getting public key from hadoopnamenode
    public_key = sudo('cat /home/ubuntu/.ssh/id_rsa.pub')

    env.host_string = hadoop_cluster.getNode(c.saltmaster).ip_address

    #Issuing a minion blast of public key to all hadoop nodes to enable passwordless login.
    minion_cmd = "echo '{0}' >> /home/ubuntu/.ssh/authorized_keys".format(public_key)
    sudo('salt "*" cmd.run "{0}"'.format(minion_cmd))
    time.sleep(2)


@task
def install_jdk_hadoop_nodes():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.saltmaster).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    with settings(warn_only = True):
        sudo('salt "*" cmd.run "sudo apt-get update"')
        sudo('salt "*" cmd.run "sudo add-apt-repository ppa:webupd8team/java"')
        sudo('salt "*" cmd.run "echo oracle-java7-installer shared/accepted-oracle-license-v1-1 select true | sudo /usr/bin/debconf-set-selections"')
        sudo('salt "*" cmd.run "sudo apt-get update && sudo apt-get install -y oracle-jdk7-installer"')
        sudo('salt "*" cmd.run "sudo apt-get -f -y -q install"')


@task
def install_hadoop_packages():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.saltmaster).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    sudo('salt "*" cmd.run "wget https://dist.apache.org/repos/dist/release/hadoop/common/hadoop-2.7.3/hadoop-2.7.3.tar.gz -P /home/ubuntu"')
    sudo('salt "*" cmd.run "tar -xzvf /home/ubuntu/hadoop-2.7.3.tar.gz -C /home/ubuntu"')
    sudo('salt "*" cmd.run "mv /home/ubuntu/hadoop-2.7.3 /home/ubuntu/hadoop"')
    sudo('salt "*" cmd.run "rm -rf /home/ubuntu/hadoop-2.7.3.tar.gz"')
    #changing the hadoop directory owner to ubuntu.
    sudo('salt "*" cmd.run "sudo chown -R ubuntu /home/ubuntu/hadoop"')
    cmd = "echo '{0}' >> /home/ubuntu/.bashrc".format("export HADOOP_CONF=/home/ubuntu/hadoop/etc/hadoop")
    sudo('salt "*" cmd.run "{0}"'.format(cmd))
    cmd = "echo '{0}' >> /home/ubuntu/.bashrc".format("export HADOOP_PREFIX=/home/ubuntu/hadoop")
    sudo('salt "*" cmd.run "{0}"'.format(cmd))
    cmd = "echo '{0}' >> /home/ubuntu/.bashrc".format("export JAVA_HOME=/usr/lib/jvm/java-7-oracle")
    sudo('salt "*" cmd.run "{0}"'.format(cmd))
    cmd = "echo '{0}' >> /home/ubuntu/.bashrc".format("export PATH='$'PATH:'$'HADOOP_PREFIX/bin")
    sudo('salt "*" cmd.run "{0}"'.format(cmd))


@task
def deploy_hadoop_config():
    hadoop_cluster = HadoopCluster()
    hadoopnamenode = hadoop_cluster.getNode(c.hadoop_namenode).dns_name
    hadoopnamenode_privateip = hadoop_cluster.getNode(c.hadoop_namenode).private_ip_address

    hadoop_env_command = "sed -i -e s/'\\\${JAVA_HOME}'/'\\\/usr\\\/lib\\\/jvm\\\/java-7-oracle'/ /home/ubuntu/hadoop/etc/hadoop/hadoop-env.sh"
    core_site_text = """<?xml version=\\""1.0\\"" encoding=\\""UTF-8\\""?>
                        <?xml-stylesheet type=\\""text/xsl\\"" href=\\""configuration.xsl\\""?>
                        <configuration>
                            <property>
                                <name>fs.default.name</name>
                                <value>hdfs://{0}:8020</value>
                            </property>
                            <property>
                                <name>hadoop.tmp.dir</name>
                                <value>/home/ubuntu/hdfstmp</value>
                            </property>
                        </configuration>""".format(hadoopnamenode)

    hdfs_site_text = """<?xml version=\\""1.0\\"" encoding=\\""UTF-8\\""?>
                        <?xml-stylesheet type=\\""text/xsl\\"" href=\\""configuration.xsl\\""?>
                        <configuration>
                            <property>
                                <name>dfs.replication</name>
                                <value>2</value>
                            </property>
                            <property>
                                <name>dfs.permissions</name>
                                <value>false</value>
                            </property>
                        </configuration>"""

    mapred_site_text ="""<?xml version=\\""1.0\\"" encoding=\\""UTF-8\\""?>
                        <?xml-stylesheet type=\\""text/xsl\\"" href=\\""configuration.xsl\\""?>
                        <configuration>
                            <property>
                                <name>mapreduce.framework.name</name>
                                <value>yarn</value>
                            </property>
                            <!--<property>
                                <name>mapred.job.tracker</name>
                                <value>hdfs://{0}:8021</value>
                            </property>-->
                        </configuration>""".format(hadoopnamenode)

    yarn_site_text ="""<?xml version=\\""1.0\\"" encoding=\\""UTF-8\\""?>
                        <?xml-stylesheet type=\\""text/xsl\\"" href=\\""configuration.xsl\\""?>
                        <configuration>
                            <property>
                                <name>yarn.resourcemanager.hostname</name>
                                <value>{0}</value>
                            </property>
                            <property>
                                <name>yarn.nodemanager.aux-services</name>
                                <value>mapreduce_shuffle</value>
                            </property>
                            <property>
                               <name>yarn.nodemanager.aux-services.mapreduce.shuffle.class</name>
                               <value>org.apache.hadoop.mapred.ShuffleHandler</value>
                            </property>
                            <property>
                            <name>yarn.nodemanager.local-dirs</name>
                                <value>/home/ubuntu/yarn/data</value>
                            </property>
                            <property>
                            <name>yarn.nodemanager.logs-dirs</name>
                                <value>/home/ubuntu/yarn/logs</value>
                            </property>
                        </configuration>""".format(hadoopnamenode_privateip)

    env.host_string = hadoop_cluster.getNode(c.saltmaster).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    sudo('salt "*" cmd.run "{0}"'.format(hadoop_env_command))
    core_site_command = "echo '{0}' > /home/ubuntu/hadoop/etc/hadoop/core-site.xml".format(core_site_text)
    sudo('salt "*" cmd.run "{0}"'.format(core_site_command))
    hdfs_site_command = "echo '{0}' > /home/ubuntu/hadoop/etc/hadoop/hdfs-site.xml".format(hdfs_site_text)
    sudo('salt "*" cmd.run "{0}"'.format(hdfs_site_command))
    mapred_site_command = "echo '{0}' > /home/ubuntu/hadoop/etc/hadoop/mapred-site.xml".format(mapred_site_text)
    sudo('salt "*" cmd.run "{0}"'.format(mapred_site_command))
    yarn_site_command = "echo '{0}' > /home/ubuntu/hadoop/etc/hadoop/yarn-site.xml".format(yarn_site_text)
    sudo('salt "*" cmd.run "{0}"'.format(yarn_site_command))


@task
def setup_hadoop_master_slave():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    sudo("echo {0} > /home/ubuntu/hadoop/etc/hadoop/masters".format(hadoop_cluster.getNode(c.hadoop_namenode).dns_name))
    sudo("echo {0} >> /home/ubuntu/hadoop/etc/hadoop/masters".format(hadoop_cluster.getNode(c.hadoop_secondary_namenode).dns_name))
    sudo(">/home/ubuntu/hadoop/etc/hadoop/slaves")
    for slave in c.hadoop_slaves:
        sudo("echo {0} >> /home/ubuntu/hadoop/etc/hadoop/slaves".format(hadoop_cluster.getNode(slave).dns_name))

    env.host_string = hadoop_cluster.getNode(c.hadoop_secondary_namenode).ip_address
    sudo("echo {0} > /home/ubuntu/hadoop/etc/hadoop/masters".format(hadoop_cluster.getNode(c.hadoop_namenode).dns_name))
    sudo("echo {0} >> /home/ubuntu/hadoop/etc/hadoop/masters".format(hadoop_cluster.getNode(c.hadoop_secondary_namenode).dns_name))
    sudo(">/home/ubuntu/hadoop/etc/hadoop/slaves")
    for slave in c.hadoop_slaves:
        sudo("echo {0} >> /home/ubuntu/hadoop/etc/hadoop/slaves".format(hadoop_cluster.getNode(slave).dns_name))

    for slave in c.hadoop_slaves:
        env.host_string = hadoop_cluster.getNode(slave).ip_address
        sudo("echo {0} > /home/ubuntu/hadoop/etc/hadoop/slaves".format(hadoop_cluster.getNode(slave).dns_name))


@task
def start_services_hadoop_master():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    run("/home/ubuntu/hadoop/bin/hadoop namenode -format -force")
    run("/home/ubuntu/hadoop/sbin/start-dfs.sh")
    run("/home/ubuntu/hadoop/sbin/start-yarn.sh")
    run("jps")

@task
def stop_services_hadoop_master():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    run("/home/ubuntu/hadoop/sbin/stop-dfs.sh")
    run("/home/ubuntu/hadoop/sbin/stop-yarn.sh")
    run("jps")

@task
def restart_services_hadoop_master():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    run("/home/ubuntu/hadoop/sbin/start-dfs.sh")
    run("/home/ubuntu/hadoop/sbin/start-yarn.sh")
    run("jps")

@task
def run_pi_test():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    with cd('/home/ubuntu/hadoop/share/hadoop/mapreduce'):
        run('/home/ubuntu/hadoop/bin/hadoop jar hadoop-mapreduce-examples-2.7.3.jar pi 10 1000000')

def run_wordcount_test():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    current_time = random.randint(0,10000)
    run(("/home/ubuntu/hadoop/bin/hdfs dfs -mkdir input-{0}").format(current_time))
    run(("/home/ubuntu/hadoop/bin/hdfs dfs -copyFromLocal /home/ubuntu/hadoop/README.txt input-{0}").format(current_time))
    with cd('/home/ubuntu/hadoop/share/hadoop/mapreduce'):
        run(('/home/ubuntu/hadoop/bin/hadoop jar hadoop-mapreduce-examples-2.7.3.jar wordcount input-{0} output-{0}').format(current_time))

@task
def install_hive():
    hadoop_cluster = HadoopCluster()
    env.host_string = hadoop_cluster.getNode(c.hadoop_namenode).ip_address
    env.user = c.aws_user
    env.key_filename = c.aws_key_location
    with cd('/home/ubuntu/'):
        run('wget http://apache.arvixe.com/hive/stable/apache-hive-1.2.1-bin.tar.gz')
        run('tar -xzvf apache-hive-1.2.1-bin.tar.gz')
        run('cd apache-hive-1.2.1-bin')
        cmd = "echo '{0}' >> /home/ubuntu/.bashrc".format("export HIVE_HOME=/home/ubuntu/apache-hive-1.2.1-bin")
        run(cmd)
        cmd = "echo '{0}' >> /home/ubuntu/.bashrc".format("export PATH=$PATH:$HIVE_HOME/bin")
        run(cmd)


@task
def provision_hadoop_cluster():
    #execute(create_aws_hadoop_cluster)
    execute(update_config)
    #execute(stop_services_hadoop_master)
    #execute(install_salt)
    #execute(setup_hadoop_nodes_access)
    #execute(install_jdk_hadoop_nodes)
    #execute(install_hadoop_packages)
    #execute(deploy_hadoop_config)
    #execute(setup_hadoop_master_slave)
    #execute(start_services_hadoop_master)
    #execute(run_pi_test)
    #execute(stop_services_hadoop_master)
    #execute(restart_services_hadoop_master)
    #execute(run_pi_test)
    execute(run_wordcount_test)




