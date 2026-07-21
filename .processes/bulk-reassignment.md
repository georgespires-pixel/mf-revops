---
id: bulk-reassignment
schema_version: 2
diagram: bpmn
name: Bulk reassignment of contacts, leads, and deals
owner: RevOps
status: captured
frequency: event-driven
duration: ~76 hours calendar per run (~3.5 hrs active + ~3 day approval wait)
trigger: JIRA ticket from regional head OR the departing employee (employee name, departure date, destination owner(s), split preference)
created: 2026-07-21
updated: 2026-07-21

# Time burden — schema v2 (all values in minutes)
time:
  per_run_minutes: 210            # ~3.5 hrs active hands-on RevOps work per run (calendar ~76 hrs incl. 3-day approval wait)
  runs_per_month: 2               # ~2 reassignments per month
  per_month_minutes: 420          # = 210 × 2 = 7 hrs/mo active
  notes: "Calendar time per run ~76 hrs, dominated by the ~3-day regional-head approval wait; active hands-on is only 3-4 hrs. Workflow-building can run in parallel with the approval wait. Approval wait only becomes friction if the departure date is tight."

scores:
  complexity:
  complexity_proposed:
  complexity_rationale:
  importance:
  importance_proposed:
  importance_rationale:
  impact:
  impact_proposed:
  impact_rationale:
provenance:
  name: confirmed
  owner: confirmed
  trigger: confirmed
  frequency: confirmed
  duration: confirmed
  time_per_run_minutes: confirmed
  runs_per_month: confirmed
---

# Bulk reassignment of contacts, leads, and deals

## Identity
- **Owner:** RevOps (Executor); Regional Head (Approver)  *(confirmed)*
- **Frequency:** Event-driven — ~2 per month, on employee departure or extended leave  *(confirmed)*
- **Trigger:** JIRA ticket created by regional head OR the departing employee, including employee name, departure date, destination owner(s), and split preference (equal/unequal/random)  *(confirmed)*
- **Duration:** ~76 hours calendar per run (~3.5 hrs active hands-on + ~3 day approval wait)  *(confirmed)*

## Time Burden
- **Per run:** 210 minutes active (~3.5 hours hands-on); ~76 hours calendar including approval wait  *(confirmed)*
- **Runs per month:** 2  *(confirmed)*
- **Per month:** 420 minutes (~7 hours active)
- **Per year:** 84 hours active
- **Notes:** Calendar load is dominated by the ~3-day regional-head approval wait, not active effort. Workflow-building can overlap the approval wait. Approval wait only becomes a pain point when the departure date is tight.

## Steps

1. **JIRA ticket received** *(confirmed)*
   - id: Event_ticket_received
   - type: start
   - notes: Raised by the regional head or the departing employee. Should include employee name, departure date, destination owner(s), split preference.
2. **Validate ticket completeness** *(confirmed)*
   - id: Task_validate_ticket
   - type: task
   - notes: RevOps checks for employee name, departure date, destination owner(s), split preference.
3. **Info complete?** *(confirmed)*
   - id: Gateway_info_complete
   - type: decision
   - gateway: xor
   - branches:
     - "No — missing fields" → Task_clarify
     - "Yes" → Task_build_segments
4. **Request clarification** *(confirmed)*
   - id: Task_clarify
   - type: task
   - notes: RevOps clarifies missing fields via ticket comment, then re-validates.
5. **Build segments (contact + deal)** *(confirmed)*
   - id: Task_build_segments
   - type: task
   - notes: RevOps builds active segment(s) filtered by current contact owner + jurisdiction + exclusions (disqualified, blacklisted, unsubscribed). Optional static segment copy preserves original owner history.
6. **Send segments to regional head** *(confirmed)*
   - id: Task_send_segments
   - type: task
   - notes: RevOps shares segment link(s) for approval. From here, workflow-building runs in parallel with the approval wait.
7. **Build workflows (contact + deal)** *(confirmed)*
   - id: Task_build_workflows
   - type: task
   - notes: RevOps clones workflow templates; configures contact-owner reassignment (split logic) + deal-owner reassignment. Lead owners auto-update from contact owner — no separate lead workflow. Workflows linked in the ticket. Runs in parallel with the approval wait.
8. **Segments approved?** *(confirmed)*
   - id: Gateway_segments_approved
   - type: decision
   - gateway: xor
   - notes: Regional head reviews the shared segment link(s).
   - branches:
     - "No" → Task_revise_segments
     - "Yes" → Gateway_ready_to_check
9. **Revise segments** *(confirmed)*
   - id: Task_revise_segments
   - type: task
   - notes: RevOps adjusts segment filters/logic and re-sends for approval.
10. **Ready for final check?** *(confirmed)*
    - id: Gateway_ready_to_check
    - type: decision
    - gateway: xor
    - notes: Join point — proceeds once segments are approved AND workflows are built.
    - branches:
      - "workflows built" → Task_final_check
      - "segments approved" → Task_final_check
11. **Final check (logic, counts, exclusions)** *(confirmed)*
    - id: Task_final_check
    - type: task
    - notes: RevOps verifies logic, counts, exclusions; confirms no gaps missed.
12. **Regional head approves?** *(confirmed)*
    - id: Gateway_final_approval
    - type: decision
    - gateway: xor
    - notes: Regional head gives final sign-off on the reassignment.
    - branches:
      - "No" → Task_revise_workflows
      - "Yes" → Task_activate
13. **Revise workflows** *(confirmed)*
    - id: Task_revise_workflows
    - type: task
    - notes: RevOps adjusts workflow logic and re-runs the final check.
14. **Activate workflows (on schedule)** *(confirmed)*
    - id: Task_activate
    - type: task
    - notes: RevOps waits for regional-head instruction on timing (day of departure or after), then turns on both workflows. Workflows are reversible.
15. **Reassignment complete** *(confirmed)*
    - id: Event_complete
    - type: end
    - notes: RevOps posts a status update to the ticket confirming completion.

## Teams

| Actor | Role | Actions |
|---|---|---|
| RevOps | Executor | Validates ticket, builds segments, builds workflows, performs final check, activates workflows  *(confirmed)* |
| Regional Head | Approver | Submits ticket or confirms intent, approves segment lists, approves workflow logic, authorizes activation timing  *(confirmed)* |

## Inputs / Outputs

### Inputs
- JIRA ticket with employee name, departure date, destination owner(s), split preference — from regional head or departing employee  *(confirmed)*
- HubSpot records: current contacts, leads, and deals owned by the departing employee (unfiltered initially)  *(confirmed)*

### Outputs
- Reassigned contact records in HubSpot (contact owner updated per split logic) — to HubSpot  *(confirmed)*
- Reassigned deal records in HubSpot (deal owner updated) — to HubSpot  *(confirmed)*
- Reassigned lead records in HubSpot (lead owner auto-updated from contact owner) — to HubSpot  *(confirmed)*
- Audit trail in JIRA (segment links, workflow links, execution timestamp) — to JIRA  *(confirmed)*
- Final status update to regional head (completion confirmation) — to JIRA  *(confirmed)*

## Tools

- JIRA — ticket intake, approval tracking, audit trail (steps 1, 2, 4, 15)  *(confirmed)*
- HubSpot — segment creation, workflow orchestration, record ownership updates (steps 5–7, 9, 11, 13, 14)  *(confirmed)*

## Pain Points

- Approval wait (~3 days) — only an issue if it extends further or the departure date is tight  *(confirmed)*
- Manual segment cloning — acceptable, not a burden  *(confirmed)*
- Workflow cloning errors — none experienced  *(confirmed)*
- Data accuracy issues — none experienced  *(confirmed)*
- Overall friction is minimal; process runs smoothly  *(confirmed)*

## Diagram

```bpmn
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
                  id="Definitions_bulk-reassignment"
                  targetNamespace="http://example.com/bulk-reassignment">
  <bpmn:process id="Process_bulk_reassignment" isExecutable="false">
    <bpmn:startEvent id="Event_ticket_received" name="JIRA ticket received">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:task id="Task_validate_ticket" name="Validate ticket completeness">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:incoming>Flow_back_validate</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:task>
    <bpmn:exclusiveGateway id="Gateway_info_complete" name="Info complete?">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_clarify</bpmn:outgoing>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:task id="Task_clarify" name="Request clarification">
      <bpmn:incoming>Flow_clarify</bpmn:incoming>
      <bpmn:outgoing>Flow_back_validate</bpmn:outgoing>
    </bpmn:task>
    <bpmn:task id="Task_build_segments" name="Build segments (contact + deal)">
      <bpmn:incoming>Flow_3</bpmn:incoming>
      <bpmn:outgoing>Flow_4</bpmn:outgoing>
    </bpmn:task>
    <bpmn:task id="Task_send_segments" name="Send segments to regional head">
      <bpmn:incoming>Flow_4</bpmn:incoming>
      <bpmn:incoming>Flow_back_send</bpmn:incoming>
      <bpmn:outgoing>Flow_5</bpmn:outgoing>
      <bpmn:outgoing>Flow_5b</bpmn:outgoing>
    </bpmn:task>
    <bpmn:task id="Task_build_workflows" name="Build workflows (contact + deal)">
      <bpmn:incoming>Flow_5</bpmn:incoming>
      <bpmn:outgoing>Flow_6</bpmn:outgoing>
    </bpmn:task>
    <bpmn:exclusiveGateway id="Gateway_segments_approved" name="Segments approved?">
      <bpmn:incoming>Flow_5b</bpmn:incoming>
      <bpmn:outgoing>Flow_revise_segments</bpmn:outgoing>
      <bpmn:outgoing>Flow_7</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:task id="Task_revise_segments" name="Revise segments">
      <bpmn:incoming>Flow_revise_segments</bpmn:incoming>
      <bpmn:outgoing>Flow_back_send</bpmn:outgoing>
    </bpmn:task>
    <bpmn:exclusiveGateway id="Gateway_ready_to_check" name="Ready for final check?">
      <bpmn:incoming>Flow_6</bpmn:incoming>
      <bpmn:incoming>Flow_7</bpmn:incoming>
      <bpmn:outgoing>Flow_8</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:task id="Task_final_check" name="Final check (logic, counts, exclusions)">
      <bpmn:incoming>Flow_8</bpmn:incoming>
      <bpmn:incoming>Flow_back_check</bpmn:incoming>
      <bpmn:outgoing>Flow_9</bpmn:outgoing>
    </bpmn:task>
    <bpmn:exclusiveGateway id="Gateway_final_approval" name="Regional head approves?">
      <bpmn:incoming>Flow_9</bpmn:incoming>
      <bpmn:outgoing>Flow_revise_workflows</bpmn:outgoing>
      <bpmn:outgoing>Flow_10</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:task id="Task_revise_workflows" name="Revise workflows">
      <bpmn:incoming>Flow_revise_workflows</bpmn:incoming>
      <bpmn:outgoing>Flow_back_check</bpmn:outgoing>
    </bpmn:task>
    <bpmn:task id="Task_activate" name="Activate workflows (on schedule)">
      <bpmn:incoming>Flow_10</bpmn:incoming>
      <bpmn:outgoing>Flow_11</bpmn:outgoing>
    </bpmn:task>
    <bpmn:endEvent id="Event_complete" name="Reassignment complete">
      <bpmn:incoming>Flow_11</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Event_ticket_received" targetRef="Task_validate_ticket" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_validate_ticket" targetRef="Gateway_info_complete" />
    <bpmn:sequenceFlow id="Flow_clarify" name="No" sourceRef="Gateway_info_complete" targetRef="Task_clarify" />
    <bpmn:sequenceFlow id="Flow_back_validate" sourceRef="Task_clarify" targetRef="Task_validate_ticket" />
    <bpmn:sequenceFlow id="Flow_3" name="Yes" sourceRef="Gateway_info_complete" targetRef="Task_build_segments" />
    <bpmn:sequenceFlow id="Flow_4" sourceRef="Task_build_segments" targetRef="Task_send_segments" />
    <bpmn:sequenceFlow id="Flow_5" sourceRef="Task_send_segments" targetRef="Task_build_workflows" />
    <bpmn:sequenceFlow id="Flow_5b" sourceRef="Task_send_segments" targetRef="Gateway_segments_approved" />
    <bpmn:sequenceFlow id="Flow_revise_segments" name="No" sourceRef="Gateway_segments_approved" targetRef="Task_revise_segments" />
    <bpmn:sequenceFlow id="Flow_back_send" sourceRef="Task_revise_segments" targetRef="Task_send_segments" />
    <bpmn:sequenceFlow id="Flow_6" sourceRef="Task_build_workflows" targetRef="Gateway_ready_to_check" />
    <bpmn:sequenceFlow id="Flow_7" name="Yes" sourceRef="Gateway_segments_approved" targetRef="Gateway_ready_to_check" />
    <bpmn:sequenceFlow id="Flow_8" sourceRef="Gateway_ready_to_check" targetRef="Task_final_check" />
    <bpmn:sequenceFlow id="Flow_9" sourceRef="Task_final_check" targetRef="Gateway_final_approval" />
    <bpmn:sequenceFlow id="Flow_revise_workflows" name="No" sourceRef="Gateway_final_approval" targetRef="Task_revise_workflows" />
    <bpmn:sequenceFlow id="Flow_back_check" sourceRef="Task_revise_workflows" targetRef="Task_final_check" />
    <bpmn:sequenceFlow id="Flow_10" name="Yes" sourceRef="Gateway_final_approval" targetRef="Task_activate" />
    <bpmn:sequenceFlow id="Flow_11" sourceRef="Task_activate" targetRef="Event_complete" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_bulk_reassignment">
      <bpmndi:BPMNShape id="Event_ticket_received_di" bpmnElement="Event_ticket_received">
        <dc:Bounds x="50" y="200" width="36" height="36" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="30" y="240" width="78" height="27" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_validate_ticket_di" bpmnElement="Task_validate_ticket">
        <dc:Bounds x="120" y="178" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Gateway_info_complete_di" bpmnElement="Gateway_info_complete" isMarkerVisible="true">
        <dc:Bounds x="270" y="193" width="50" height="50" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="262" y="250" width="66" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_clarify_di" bpmnElement="Task_clarify">
        <dc:Bounds x="245" y="78" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_build_segments_di" bpmnElement="Task_build_segments">
        <dc:Bounds x="370" y="178" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_send_segments_di" bpmnElement="Task_send_segments">
        <dc:Bounds x="520" y="178" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_build_workflows_di" bpmnElement="Task_build_workflows">
        <dc:Bounds x="520" y="320" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Gateway_segments_approved_di" bpmnElement="Gateway_segments_approved" isMarkerVisible="true">
        <dc:Bounds x="670" y="193" width="50" height="50" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="660" y="250" width="70" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_revise_segments_di" bpmnElement="Task_revise_segments">
        <dc:Bounds x="645" y="78" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Gateway_ready_to_check_di" bpmnElement="Gateway_ready_to_check" isMarkerVisible="true">
        <dc:Bounds x="795" y="193" width="50" height="50" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="785" y="250" width="70" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_final_check_di" bpmnElement="Task_final_check">
        <dc:Bounds x="900" y="178" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Gateway_final_approval_di" bpmnElement="Gateway_final_approval" isMarkerVisible="true">
        <dc:Bounds x="1050" y="193" width="50" height="50" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="1040" y="250" width="70" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_revise_workflows_di" bpmnElement="Task_revise_workflows">
        <dc:Bounds x="1025" y="78" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_activate_di" bpmnElement="Task_activate">
        <dc:Bounds x="1150" y="178" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Event_complete_di" bpmnElement="Event_complete">
        <dc:Bounds x="1300" y="200" width="36" height="36" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="1280" y="240" width="78" height="27" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="Flow_1_di" bpmnElement="Flow_1">
        <di:waypoint x="86" y="218" /><di:waypoint x="120" y="218" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_2_di" bpmnElement="Flow_2">
        <di:waypoint x="220" y="218" /><di:waypoint x="270" y="218" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_clarify_di" bpmnElement="Flow_clarify">
        <di:waypoint x="295" y="193" /><di:waypoint x="295" y="158" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="301" y="170" width="15" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_back_validate_di" bpmnElement="Flow_back_validate">
        <di:waypoint x="245" y="118" /><di:waypoint x="170" y="118" /><di:waypoint x="170" y="178" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_3_di" bpmnElement="Flow_3">
        <di:waypoint x="320" y="218" /><di:waypoint x="370" y="218" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="335" y="200" width="20" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_4_di" bpmnElement="Flow_4">
        <di:waypoint x="470" y="218" /><di:waypoint x="520" y="218" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_5_di" bpmnElement="Flow_5">
        <di:waypoint x="570" y="258" /><di:waypoint x="570" y="320" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_5b_di" bpmnElement="Flow_5b">
        <di:waypoint x="620" y="218" /><di:waypoint x="670" y="218" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_revise_segments_di" bpmnElement="Flow_revise_segments">
        <di:waypoint x="695" y="193" /><di:waypoint x="695" y="158" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="701" y="170" width="15" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_back_send_di" bpmnElement="Flow_back_send">
        <di:waypoint x="645" y="118" /><di:waypoint x="570" y="118" /><di:waypoint x="570" y="178" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_6_di" bpmnElement="Flow_6">
        <di:waypoint x="620" y="360" /><di:waypoint x="820" y="360" /><di:waypoint x="820" y="243" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_7_di" bpmnElement="Flow_7">
        <di:waypoint x="720" y="218" /><di:waypoint x="795" y="218" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="745" y="200" width="20" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_8_di" bpmnElement="Flow_8">
        <di:waypoint x="845" y="218" /><di:waypoint x="900" y="218" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_9_di" bpmnElement="Flow_9">
        <di:waypoint x="1000" y="218" /><di:waypoint x="1050" y="218" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_revise_workflows_di" bpmnElement="Flow_revise_workflows">
        <di:waypoint x="1075" y="193" /><di:waypoint x="1075" y="158" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="1081" y="170" width="15" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_back_check_di" bpmnElement="Flow_back_check">
        <di:waypoint x="1025" y="118" /><di:waypoint x="950" y="118" /><di:waypoint x="950" y="178" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_10_di" bpmnElement="Flow_10">
        <di:waypoint x="1100" y="218" /><di:waypoint x="1150" y="218" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="1115" y="200" width="20" height="14" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_11_di" bpmnElement="Flow_11">
        <di:waypoint x="1250" y="218" /><di:waypoint x="1300" y="218" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
```
