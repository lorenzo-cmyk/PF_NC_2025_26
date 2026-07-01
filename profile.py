"""eTran L1 Switch Profile

This profile allocates a variable number of xl170 bare-metal nodes and a 
dedicated, physically managed Mellanox SN2410 switch on the Utah cluster.
This enables direct root SSH access to the switch OS (Cumulus Linux) to 
manually configure ECN, buffering, or RED/WRED parameters.
"""

import geni.portal as portal
import geni.rspec.pg as pg

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
# By treating it as a RawPC with hardware_type "mellanox", CloudLab will give 
# us a physical SN2410 switch running Cumulus Linux that we can SSH into.
switch = request.RawPC("sw1")
switch.hardware_type = "mellanox"
switch.Site("utah")

# 2. PROVISION AND ROUTE THE BARE-METAL SERVERS
for i in range(params.nodeCount):
    name = "node" + str(i)
    node = request.RawPC(name)
    node.hardware_type = "xl170"
    node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD"
    
    # Allocate a 16 GB blockstore mounted at /mydata
    bs = node.Blockstore("bs-" + str(i), "/mydata")
    bs.size = "16GB"
    bs.placement = "any"
    
    node.Site("utah")
    
    # Create the raw experimental interface on the server
    iface = node.addInterface("eth1")
    
    # Explicitly add the 10.10.1.x IP addressing matching the eTran test suites
    ip_addr = "10.10.1.{}".format(i + 1)
    iface.addAddress(pg.IPv4Address(ip_addr, "255.255.255.0"))
    
    # Create the corresponding interface port on the Mellanox switch (e.g., swp1, swp2)
    sw_iface = switch.addInterface("swp" + str(i + 1))
    
    # DRAW A LITERAL PHYSICAL WIRE BETWEEN SERVER PORT AND SWITCH PORT
    # L1Link creates point-to-point physical patches at 25 Gbps
    link = request.L1Link("l1link-" + str(i))
    link.addInterface(iface)
    link.addInterface(sw_iface)

# Print generated RSpec back to the CloudLab manager
pc.printRequestRSpec()