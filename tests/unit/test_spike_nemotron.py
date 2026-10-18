from reliability_agent.contracts.models import ActionName, FaultType
from reliability_agent.nemotron.planner import build_packet
from reliability_agent.policy import PolicyGate
from scripts import spike_nemotron


def test_defocus_spike_packet_matches_offered_for_without_autofocus():
    capabilities = ["exposure", "profiles", "restart"]
    fault = FaultType.FOCUS_DRIFT
    gate = PolicyGate()
    incident = spike_nemotron.make_incident(
        fault, 0, capabilities=capabilities
    )

    packet = build_packet(incident, gate)
    offered = [ActionName(action["name"]) for action in packet["allowed_actions"]]

    assert offered == gate.offered_for(capabilities, [fault])
    assert ActionName.TRIGGER_AUTOFOCUS not in offered
    assert ActionName.SET_EXPOSURE_BOUNDED not in offered
