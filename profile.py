"""eTran Managed Switch Profile

This profile allocates a variable number of xl170 bare-metal nodes and a 
dedicated, physically managed Mellanox SN2410 switch on the Utah cluster.
"""

import geni.portal as portal
import geni.rspec.pg as pg

pc = portal.Context()

pc.defineParameter("nodeCount", "Number of xl170 Nodes", 
                   portal.ParameterType.INTEGER, 2,
                   [(2, "2"), (3, "3"), (4, "4"), (5, "5"),
                    (6, "6"), (7, "7"), (8, "8"), (9, "9"), (10, "10")],
                   longDescription="Number of compute nodes connected to the switch.")

params = pc.bindParameters()
pc.verifyParameters()

request = pc.makeRequestRSpec()

# 1. PROVISION THE MELLANOX SWITCH
switch = request.RawPC("sw1")
switch.hardware_type = "mlnx-sn2410" 
switch.Site("utah")

# 2. PROVISION AND ROUTE THE BARE-METAL SERVERS
for i in range(params.nodeCount):
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
    
    # Create the corresponding interface port on the switch (swp1, swp2...)
    sw_iface = switch.addInterface("swp" + str(i + 1))
    
    # 3. LINK THE SERVER TO THE SWITCH
    # A standard Link between two RawPCs automatically provisions a physical path
    link = request.Link("link-" + str(i))
    link.addInterface(iface)
    link.addInterface(sw_iface)

pc.printRequestRSpec()