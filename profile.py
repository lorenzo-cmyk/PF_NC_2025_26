"""eTran Managed Switch Profile

This profile allocates a variable number of xl170 bare-metal nodes and a 
dedicated, physically managed Mellanox SN2410 switch on the Utah cluster.
"""

import geni.portal as portal
import geni.rspec.pg as pg

pc = portal.Context()

request = pc.makeRequestRSpec()

node_count = 4

# Node experiment network settings
node_subnet = "192.168.6."
node_netmask = "255.255.255.0"

# 1. PROVISION THE BARE-METAL SERVERS
lan = request.LAN("lan")

for i in range(node_count):
    name = "node" + str(i)
    node = request.RawPC(name)
    node.hardware_type = "xl170"
    node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD"
    
    bs = node.Blockstore("bs-" + str(i), "/mydata")
    bs.size = "16GB"
    bs.placement = "any"
    
    node.Site("utah")
    
    # Create the experimental interface on the server
    iface = node.addInterface("eth1")
    iface.addAddress(pg.IPv4Address(node_subnet + str(i + 1), node_netmask))

    # Add each node interface to a shared experimental LAN.
    lan.addInterface(iface)

pc.printRequestRSpec()