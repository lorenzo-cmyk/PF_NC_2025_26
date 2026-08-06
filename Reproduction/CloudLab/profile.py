"""eTran reproduction profile.

Allocates a variable number of xl170 nodes (Ubuntu 22.04, 16 GB blockstore
at /mydata) on a 25 GbE LAN forced through a single physical switch via
setNoInterSwitchLinks() and trivial_ok=False, bypassing the NetScout fabric's
10 GbE cap. The switch is not exposed as a managed component; get management
access via the experiment status page or testbed-ops.

Reproduces: Chen et al., "eTran: Extensible Kernel Transport with eBPF,"
NSDI 2025. https://www.usenix.org/conference/nsdi25/presentation/chen-zhongjie

NOTE: Parsed by Python 2 on CloudLab's portal -- ASCII only. CloudLab's
geni-lib differs from PyPI 0.9.9.4; local testing is not useful -- debug via
the portal's "Source" tab.
"""

import geni.portal as portal
import geni.rspec.pg as pg

# Portal context (user-configurable parameters) and RSpec request.
pc = portal.Context()
request = pc.makeRequestRSpec()

# Number of nodes (2-10).
pc.defineParameter(
    "nodeCount",
    "Number of Nodes",
    portal.ParameterType.INTEGER,
    2,
    [
        (2, "2"),
        (3, "3"),
        (4, "4"),
        (5, "5"),
        (6, "6"),
        (7, "7"),
        (8, "8"),
        (9, "9"),
        (10, "10"),
    ],
    longDescription="Number of xl170 nodes (2 to 10).",
)

# Bind user-provided values and validate.
params = pc.bindParameters()
pc.verifyParameters()

# Single-switch LAN (no direct cable; all ports on the same switch).
lan = request.LAN()
lan.bandwidth = 25000000
lan.trivial_ok = False
lan.setNoInterSwitchLinks()

# Instantiate nodes, wire to the LAN, attach blockstores.
for i in range(params.nodeCount):
    name = "node" + str(i)

    # xl170 bare-metal node, Ubuntu 22.04.
    node = request.RawPC(name)
    node.hardware_type = "xl170"
    node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD"

    # Static IP on the experimental LAN.
    iface = node.addInterface("eth1")
    iface.addAddress(pg.IPv4Address("192.168.6." + str(i + 1), "255.255.255.0"))
    lan.addInterface(iface)

    # 16 GB blockstore at /mydata.
    bs = node.Blockstore(name + "-bs", "/mydata")
    bs.size = "16GB"
    bs.placement = "any"

# Emit the RSpec.
pc.printRequestRSpec(request)
