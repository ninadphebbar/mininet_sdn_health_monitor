"""Telemetry-aware SDN controller (Ryu / OS-Ken, OpenFlow 1.3).

A learning switch plus **flow prioritization for health-telemetry traffic**.

Telemetry is identified by its UDP destination port(s). Prioritized packets get
the OpenFlow ``set_queue`` action, steering them into the high-priority,
bandwidth-guaranteed Open vSwitch HTB queue (queue 1) on the egress port; all
other traffic stays in the best-effort queue (queue 0). The queues themselves
are created by ``topology/perf_topo.py`` (``configure_qos``).

Operating modes (environment variable ``QOS_MODE``):

  baseline  plain learning switch; nothing is prioritized  (the comparison case)
  priority  telemetry flows are *always* mapped to queue 1 (static QoS)
  dynamic   the controller polls port counters; telemetry is moved to queue 1
            only while a port is congested, and moved back when the load drops
            (hysteresis: ON >= HIGH_FRAC of capacity, OFF < LOW_FRAC twice in a row)

Other settings (environment variables):
  TELEMETRY_PORTS   comma separated UDP dst ports      default 9901
  BOTTLENECK_MBPS   capacity used for utilisation       default 10
  HIGH_FRAC / LOW_FRAC                                  default 0.80 / 0.40
  POLL_INTERVAL     port-stats period in seconds        default 0.5
  TELEMETRY_QUEUE   queue id for telemetry              default 1

Run:  QOS_MODE=dynamic ryu-manager --ofp-tcp-listen-port 6653 controller/qos_controller.py
"""
import os
import time

try:                                           # classic Ryu
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import (CONFIG_DISPATCHER, DEAD_DISPATCHER,
                                        MAIN_DISPATCHER, set_ev_cls)
    from ryu.lib import hub
    from ryu.lib.packet import ethernet, ether_types, ipv4, packet, udp
    from ryu.ofproto import ofproto_v1_3
except ImportError:                            # OS-Ken: maintained fork, same API
    from os_ken.base import app_manager
    from os_ken.controller import ofp_event
    from os_ken.controller.handler import (CONFIG_DISPATCHER, DEAD_DISPATCHER,
                                           MAIN_DISPATCHER, set_ev_cls)
    from os_ken.lib import hub
    from os_ken.lib.packet import ethernet, ether_types, ipv4, packet, udp
    from os_ken.ofproto import ofproto_v1_3

AppBase = getattr(app_manager, "RyuApp", None) or app_manager.OSKenApp   # OS-Ken renamed it

TELEMETRY_COOKIE = 0x7E1E
PRIO_L2 = 10            # generic MAC-learning flows
PRIO_TELEMETRY = 20     # telemetry-class flows (shadow the L2 flow for UDP:port)


class TelemetryQoSController(AppBase):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        env = os.environ.get
        self.mode = env("QOS_MODE", "dynamic").lower()
        if self.mode not in ("baseline", "priority", "dynamic"):
            raise ValueError("QOS_MODE must be baseline|priority|dynamic")
        self.tele_ports = [int(p) for p in env("TELEMETRY_PORTS", "9901").split(",")]
        self.tele_queue = int(env("TELEMETRY_QUEUE", "1"))
        self.cap_bps = float(env("BOTTLENECK_MBPS", "10")) * 1e6
        self.high = float(env("HIGH_FRAC", "0.80"))
        self.low = float(env("LOW_FRAC", "0.40"))
        self.poll = float(env("POLL_INTERVAL", "0.5"))

        self.datapaths = {}        # dpid -> datapath
        self.mac_to_port = {}      # dpid -> {mac: port}
        self.paths = {}            # dpid -> {(in_port, src, dst): out_port}
        self.congested = {}        # dpid -> bool
        self._below = {}           # dpid -> consecutive polls under LOW
        self._prev = {}            # (dpid, port) -> (time, tx_bytes)
        self.logger.info("CONFIG mode=%s ports=%s queue=%d cap=%.0fMbps high=%.2f low=%.2f poll=%.2fs",
                         self.mode, self.tele_ports, self.tele_queue, self.cap_bps / 1e6,
                         self.high, self.low, self.poll)
        self._running = True
        if self.mode == "dynamic":
            self.monitor_thread = hub.spawn(self._monitor)

    # ------------------------------------------------------------------ policy
    def prioritize(self, dpid):
        if self.mode == "priority":
            return True
        if self.mode == "dynamic":
            return self.congested.get(dpid, False)
        return False

    # ------------------------------------------------------------ switch setup
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _features(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, parser.OFPMatch(), actions)          # table-miss
        self.logger.info("SWITCH_UP dpid=%s", dp.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
        else:
            self.datapaths.pop(dp.id, None)

    # ------------------------------------------------------------ flow helpers
    def _add_flow(self, dp, priority, match, actions, cookie=0):
        parser, ofp = dp.ofproto_parser, dp.ofproto
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                      instructions=inst, cookie=cookie))

    def _install_telemetry_flows(self, dp, in_port, src, dst, out_port):
        """(Re)write the telemetry-class flow(s) for one L2 path.

        Re-adding a flow with identical match+priority replaces its actions, so
        a mode change is just a re-install - no packet-in needed.
        """
        parser = dp.ofproto_parser
        actions = []
        if self.prioritize(dp.id):
            actions.append(parser.OFPActionSetQueue(self.tele_queue))
        actions.append(parser.OFPActionOutput(out_port))
        for port in self.tele_ports:
            match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst,
                                    eth_type=ether_types.ETH_TYPE_IP, ip_proto=17,
                                    udp_dst=port)
            self._add_flow(dp, PRIO_TELEMETRY, match, actions, cookie=TELEMETRY_COOKIE)

    def _refresh_telemetry_flows(self, dpid):
        dp = self.datapaths.get(dpid)
        if dp is None:
            return
        for (in_port, src, dst), out_port in list(self.paths.get(dpid, {}).items()):
            self._install_telemetry_flows(dp, in_port, src, dst, out_port)

    # --------------------------------------------------------------- packet-in
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]
        eth = packet.Packet(msg.data).get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        src, dst = eth.src, eth.dst
        table = self.mac_to_port.setdefault(dp.id, {})
        table[src] = in_port
        out_port = table.get(dst, ofp.OFPP_FLOOD)

        if out_port != ofp.OFPP_FLOOD:                              # path known
            match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
            self._add_flow(dp, PRIO_L2, match, [parser.OFPActionOutput(out_port)])
            self.paths.setdefault(dp.id, {})[(in_port, src, dst)] = out_port
            self._install_telemetry_flows(dp, in_port, src, dst, out_port)

        # forward the packet that triggered us. A telemetry datagram that arrives
        # here (first packet / during a mode flip) is sent out with the right queue.
        actions = []
        pkt = packet.Packet(msg.data)
        ip, u = pkt.get_protocol(ipv4.ipv4), pkt.get_protocol(udp.udp)
        if (ip and u and u.dst_port in self.tele_ports and self.prioritize(dp.id)
                and out_port != ofp.OFPP_FLOOD):
            actions.append(parser.OFPActionSetQueue(self.tele_queue))
        actions.append(parser.OFPActionOutput(out_port))
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                        in_port=in_port, actions=actions, data=data))

    # ------------------------------------------------- congestion monitor (dynamic)
    def _monitor(self):
        while self._running:
            for dp in list(self.datapaths.values()):
                parser, ofp = dp.ofproto_parser, dp.ofproto
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
            hub.sleep(self.poll)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        now = time.time()
        peak = 0.0
        for st in ev.msg.body:
            if st.port_no > ofp.OFPP_MAX:
                continue
            key = (dp.id, st.port_no)
            prev = self._prev.get(key)
            self._prev[key] = (now, st.tx_bytes)
            if prev and now > prev[0]:
                rate = 8.0 * (st.tx_bytes - prev[1]) / (now - prev[0])
                peak = max(peak, rate / self.cap_bps)
        self._update_state(dp.id, peak, now)

    def _update_state(self, dpid, peak_util, now):
        """Hysteresis state machine; split out so it can be unit-tested."""
        was = self.congested.get(dpid, False)
        if not was and peak_util >= self.high:
            self.congested[dpid] = True
            self._below[dpid] = 0
        elif was:
            self._below[dpid] = self._below.get(dpid, 0) + 1 if peak_util < self.low else 0
            if self._below[dpid] >= 2:
                self.congested[dpid] = False
        if self.congested.get(dpid, False) != was:
            self.logger.info("CONGESTION_%s dpid=%s util=%.2f t=%.3f",
                             "ON" if not was else "OFF", dpid, peak_util, now)
            self._refresh_telemetry_flows(dpid)
