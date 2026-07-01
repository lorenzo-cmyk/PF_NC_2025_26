"""eTran L1 Switch Profile

This profile allocates a variable number of xl170 bare-metal nodes and a 
dedicated, physically managed Mellanox SN2410 switch on the Utah cluster.
This enables direct root SSH access to the switch OS (Cumulus Linux) to 
manually configure ECN, buffering, or RED/WRED parameters.
"""

import geni.portal as portal
import geni.rspec.pg as pg
import geni.rspec.emulab as emulab

# Create a portal context for parameter handling
pc = portal.Context()

# Define an integer slider parameter for node scale (Default: 2, Bounds: 2-10)
pc.defineParameter("nodeCount", "Number of xl170 Nodes", 
                   portal.ParameterType.INTEGER, 2,
                   [(2, "2"), (3, "3"), (4, "4"), (5, "5"),
                    (6, "6"), (7, "7"), (8, "8"), (9, "9"), (10, "10")],
                   longDescription="Number of compute nodes connected to the switch.")

# Retrieve and verify user choices
params = pc.bindParameters()
pc.verifyParameters()

# Initialize the RSpec request payload
request = pc.makeRequestRSpec()

# 1. PROVISION THE MELLANOX SWITCH AS A MANAGED NODE
# On the Utah cluster, 'mellanox' indicates the SN2410 25GbE/100GbE physical switch
switch = request.Link("sw1")
switch.kind = "switch"
switch.component_id = "switch"
switch.Site("utah")

# 2. PROVISION AND ROUTE THE BARE-METAL SERVERS
for i in range(params.nodeCount):
    name = "node" + str(i)
    node = request.RawPC(name)
    node.hardware_type = "xl170"
    node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD"
    
    # Allocate a 16 GB blockstore mounted at /mydata for kernel building
    bs = node.Blockstore("bs-" + str(i), "/mydata")
    bs.size = "16GB"
    bs.placement = "any"
    
    node.Site("utah")
    
    # Create the raw experimental interface on the server
    iface = node.addInterface("eth1")
    
    # Explicitly add the 10.10.1.x IP addressing matching the eTran test suites
    ip_addr = "10.10.1.{}".format(i + 1)
    iface.addAddress(pg.IPv4Address(ip_addr, "255.255.255.0"))
    
    # DRAW A LITERAL PHYSICAL WIRE BETWEEN SERVER PORT AND SWITCH PORT
    # L1Link creates point-to-point physical patches at 25 Gbps
    link = request.L1Link("l1link-" + name)
    link.addInterface(iface)
    link.addInterface(switch.addInterface())

# Print generated RSpec back to the CloudLab manager
pc.printRequestRSpec()