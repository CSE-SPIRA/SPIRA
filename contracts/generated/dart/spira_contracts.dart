// To parse this JSON data, do
//
//     final ack = ackFromJson(jsonString);
//     final calendar = calendarFromJson(jsonString);
//     final calendarResponse = calendarResponseFromJson(jsonString);
//     final card = cardFromJson(jsonString);
//     final cardsResponse = cardsResponseFromJson(jsonString);
//     final caseRow = caseRowFromJson(jsonString);
//     final devices = devicesFromJson(jsonString);
//     final devicesResponse = devicesResponseFromJson(jsonString);
//     final episode = episodeFromJson(jsonString);
//     final episodeList = episodeListFromJson(jsonString);
//     final error = errorFromJson(jsonString);
//     final event = eventFromJson(jsonString);
//     final eventBatch = eventBatchFromJson(jsonString);
//     final eventResponse = eventResponseFromJson(jsonString);
//     final executionResponse = executionResponseFromJson(jsonString);
//     final executionResult = executionResultFromJson(jsonString);
//     final health = healthFromJson(jsonString);
//     final householdCreate = householdCreateFromJson(jsonString);
//     final householdCreated = householdCreatedFromJson(jsonString);
//     final memory = memoryFromJson(jsonString);
//     final orderAccepted = orderAcceptedFromJson(jsonString);
//     final orderEdit = orderEditFromJson(jsonString);
//     final pause = pauseFromJson(jsonString);
//     final plan = planFromJson(jsonString);
//     final planPull = planPullFromJson(jsonString);
//     final profile = profileFromJson(jsonString);
//     final rationale = rationaleFromJson(jsonString);
//     final reaction = reactionFromJson(jsonString);

import 'dart:convert';

Ack ackFromJson(String str) => Ack.fromJson(json.decode(str));

String ackToJson(Ack data) => json.encode(data.toJson());

Calendar calendarFromJson(String str) => Calendar.fromJson(json.decode(str));

String calendarToJson(Calendar data) => json.encode(data.toJson());

CalendarResponse calendarResponseFromJson(String str) => CalendarResponse.fromJson(json.decode(str));

String calendarResponseToJson(CalendarResponse data) => json.encode(data.toJson());

Card cardFromJson(String str) => Card.fromJson(json.decode(str));

String cardToJson(Card data) => json.encode(data.toJson());

CardsResponse cardsResponseFromJson(String str) => CardsResponse.fromJson(json.decode(str));

String cardsResponseToJson(CardsResponse data) => json.encode(data.toJson());

CaseRow caseRowFromJson(String str) => CaseRow.fromJson(json.decode(str));

String caseRowToJson(CaseRow data) => json.encode(data.toJson());

Devices devicesFromJson(String str) => Devices.fromJson(json.decode(str));

String devicesToJson(Devices data) => json.encode(data.toJson());

DevicesResponse devicesResponseFromJson(String str) => DevicesResponse.fromJson(json.decode(str));

String devicesResponseToJson(DevicesResponse data) => json.encode(data.toJson());

Episode episodeFromJson(String str) => Episode.fromJson(json.decode(str));

String episodeToJson(Episode data) => json.encode(data.toJson());

EpisodeList episodeListFromJson(String str) => EpisodeList.fromJson(json.decode(str));

String episodeListToJson(EpisodeList data) => json.encode(data.toJson());

Error errorFromJson(String str) => Error.fromJson(json.decode(str));

String errorToJson(Error data) => json.encode(data.toJson());

EventBatch eventFromJson(String str) => EventBatch.fromJson(json.decode(str));

String eventToJson(EventBatch data) => json.encode(data.toJson());

List<EventBatch> eventBatchFromJson(String str) => List<EventBatch>.from(json.decode(str).map((x) => EventBatch.fromJson(x)));

String eventBatchToJson(List<EventBatch> data) => json.encode(List<dynamic>.from(data.map((x) => x.toJson())));

EventResponse eventResponseFromJson(String str) => EventResponse.fromJson(json.decode(str));

String eventResponseToJson(EventResponse data) => json.encode(data.toJson());

ExecutionResponse executionResponseFromJson(String str) => ExecutionResponse.fromJson(json.decode(str));

String executionResponseToJson(ExecutionResponse data) => json.encode(data.toJson());

ExecutionResult executionResultFromJson(String str) => ExecutionResult.fromJson(json.decode(str));

String executionResultToJson(ExecutionResult data) => json.encode(data.toJson());

Health healthFromJson(String str) => Health.fromJson(json.decode(str));

String healthToJson(Health data) => json.encode(data.toJson());

HouseholdCreate householdCreateFromJson(String str) => HouseholdCreate.fromJson(json.decode(str));

String householdCreateToJson(HouseholdCreate data) => json.encode(data.toJson());

HouseholdCreated householdCreatedFromJson(String str) => HouseholdCreated.fromJson(json.decode(str));

String householdCreatedToJson(HouseholdCreated data) => json.encode(data.toJson());

Memory memoryFromJson(String str) => Memory.fromJson(json.decode(str));

String memoryToJson(Memory data) => json.encode(data.toJson());

OrderAccepted orderAcceptedFromJson(String str) => OrderAccepted.fromJson(json.decode(str));

String orderAcceptedToJson(OrderAccepted data) => json.encode(data.toJson());

OrderEdit orderEditFromJson(String str) => OrderEdit.fromJson(json.decode(str));

String orderEditToJson(OrderEdit data) => json.encode(data.toJson());

Pause pauseFromJson(String str) => Pause.fromJson(json.decode(str));

String pauseToJson(Pause data) => json.encode(data.toJson());

Plan planFromJson(String str) => Plan.fromJson(json.decode(str));

String planToJson(Plan data) => json.encode(data.toJson());

PlanPull planPullFromJson(String str) => PlanPull.fromJson(json.decode(str));

String planPullToJson(PlanPull data) => json.encode(data.toJson());

Profile profileFromJson(String str) => Profile.fromJson(json.decode(str));

String profileToJson(Profile data) => json.encode(data.toJson());

Rationale rationaleFromJson(String str) => Rationale.fromJson(json.decode(str));

String rationaleToJson(Rationale data) => json.encode(data.toJson());

Reaction reactionFromJson(String str) => Reaction.fromJson(json.decode(str));

String reactionToJson(Reaction data) => json.encode(data.toJson());


///Hub -> server after taking a new plan version: POST /v1/hub/plans/{plan_id}/ack. Reject
///only malformed tasks, never because of house state. (HUB-15)
class Ack {
    final int planVersion;
    final List<RejectedTask> rejectedTasks;
    
    ///rejected = the whole plan is unreadable; admitted = some or all tasks taken.
    final AckStatus status;

    Ack({
        required this.planVersion,
        required this.rejectedTasks,
        required this.status,
    });

    factory Ack.fromJson(Map<String, dynamic> json) => Ack(
        planVersion: json["plan_version"],
        rejectedTasks: List<RejectedTask>.from(json["rejected_tasks"].map((x) => RejectedTask.fromJson(x))),
        status: ackStatusValues.map[json["status"]]!,
    );

    Map<String, dynamic> toJson() => {
        "plan_version": planVersion,
        "rejected_tasks": List<dynamic>.from(rejectedTasks.map((x) => x.toJson())),
        "status": ackStatusValues.reverse[status],
    };
}

class RejectedTask {
    final AckRejectReason reason;
    final String taskId;

    RejectedTask({
        required this.reason,
        required this.taskId,
    });

    factory RejectedTask.fromJson(Map<String, dynamic> json) => RejectedTask(
        reason: ackRejectReasonValues.map[json["reason"]]!,
        taskId: json["task_id"],
    );

    Map<String, dynamic> toJson() => {
        "reason": ackRejectReasonValues.reverse[reason],
        "task_id": taskId,
    };
}

enum AckRejectReason {
    SCHEMA,
    UNKNOWN_DEVICE,
    UNSUPPORTED_CMD,
    VALUE_OUT_OF_RANGE
}

final ackRejectReasonValues = EnumValues({
    "schema": AckRejectReason.SCHEMA,
    "unknown_device": AckRejectReason.UNKNOWN_DEVICE,
    "unsupported_cmd": AckRejectReason.UNSUPPORTED_CMD,
    "value_out_of_range": AckRejectReason.VALUE_OUT_OF_RANGE
});


///rejected = the whole plan is unreadable; admitted = some or all tasks taken.
enum AckStatus {
    ADMITTED,
    REJECTED
}

final ackStatusValues = EnumValues({
    "admitted": AckStatus.ADMITTED,
    "rejected": AckStatus.REJECTED
});


///App -> server: PUT /v1/households/{hid}/calendar. The full list for now .. +14 days
///replaces what the server had. The server keeps only tags and drops titles. (APP-03)
class Calendar {
    final List<EventElement> events;

    Calendar({
        required this.events,
    });

    factory Calendar.fromJson(Map<String, dynamic> json) => Calendar(
        events: List<EventElement>.from(json["events"].map((x) => EventElement.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "events": List<dynamic>.from(events.map((x) => x.toJson())),
    };
}

class EventElement {
    final String end;
    
    ///Calendar event id from the app (stable).
    final String id;
    final String start;
    final String title;

    EventElement({
        required this.end,
        required this.id,
        required this.start,
        required this.title,
    });

    factory EventElement.fromJson(Map<String, dynamic> json) => EventElement(
        end: json["end"],
        id: json["id"],
        start: json["start"],
        title: json["title"],
    );

    Map<String, dynamic> toJson() => {
        "end": end,
        "id": id,
        "start": start,
        "title": title,
    };
}


///Response 202 of PUT /v1/households/{hid}/calendar. Tagging runs in the background.
///(APP-03)
class CalendarResponse {
    final int accepted;

    CalendarResponse({
        required this.accepted,
    });

    factory CalendarResponse.fromJson(Map<String, dynamic> json) => CalendarResponse(
        accepted: json["accepted"],
    );

    Map<String, dynamic> toJson() => {
        "accepted": accepted,
    };
}


///Response of GET /v1/households/{hid}/cards?since=. Cards updated after since. Use
///server_time as the next since. (APP-04)
class CardsResponse {
    final List<Card> cards;
    final String serverTime;

    CardsResponse({
        required this.cards,
        required this.serverTime,
    });

    factory CardsResponse.fromJson(Map<String, dynamic> json) => CardsResponse(
        cards: List<Card>.from(json["cards"].map((x) => Card.fromJson(x))),
        serverTime: json["server_time"],
    );

    Map<String, dynamic> toJson() => {
        "cards": List<dynamic>.from(cards.map((x) => x.toJson())),
        "server_time": serverTime,
    };
}


///Notice card for one preparation (= one intent, C-6 v2). Server -> app via GET
////v1/households/{hid}/cards. Line states follow state-mapping.md. (APP-04, APP-14)
class Card {
    
    ///Empty after stop.
    final List<CardButton> buttons;
    final String cardId;
    final String episodeId;
    
    ///From kb/intents.json, or unclassified.
    final String intentId;
    final List<LineElement> lines;
    
    ///true only for a new card or when a held card found its time. Show one local notification
    ///per (card_id, updated_at).
    final bool notify;
    
    ///Start of the linked schedule; null while waiting for a time.
    final String? startsAt;
    final bool stopped;
    final Summary summary;
    
    ///Text template id, e.g. common.v1.
    final String template;
    
    ///Card sentence (display text).
    final String text;
    final String updatedAt;

    Card({
        required this.buttons,
        required this.cardId,
        required this.episodeId,
        required this.intentId,
        required this.lines,
        required this.notify,
        required this.startsAt,
        required this.stopped,
        required this.summary,
        required this.template,
        required this.text,
        required this.updatedAt,
    });

    factory Card.fromJson(Map<String, dynamic> json) => Card(
        buttons: List<CardButton>.from(json["buttons"].map((x) => cardButtonValues.map[x]!)),
        cardId: json["card_id"],
        episodeId: json["episode_id"],
        intentId: json["intent_id"],
        lines: List<LineElement>.from(json["lines"].map((x) => LineElement.fromJson(x))),
        notify: json["notify"],
        startsAt: json["starts_at"],
        stopped: json["stopped"],
        summary: Summary.fromJson(json["summary"]),
        template: json["template"],
        text: json["text"],
        updatedAt: json["updated_at"],
    );

    Map<String, dynamic> toJson() => {
        "buttons": List<dynamic>.from(buttons.map((x) => cardButtonValues.reverse[x])),
        "card_id": cardId,
        "episode_id": episodeId,
        "intent_id": intentId,
        "lines": List<dynamic>.from(lines.map((x) => x.toJson())),
        "notify": notify,
        "starts_at": startsAt,
        "stopped": stopped,
        "summary": summary.toJson(),
        "template": template,
        "text": text,
        "updated_at": updatedAt,
    };
}

enum CardButton {
    STOP
}

final cardButtonValues = EnumValues({
    "stop": CardButton.STOP
});

class LineElement {
    final bool checked;
    final EndState? endState;
    
    ///Display text, e.g. why a line is blocked.
    final String? note;
    final LineState state;
    final String taskId;
    final String text;
    
    ///Planned time or trigger event; null while held.
    final LineWhen? when;

    LineElement({
        required this.checked,
        required this.endState,
        required this.note,
        required this.state,
        required this.taskId,
        required this.text,
        required this.when,
    });

    factory LineElement.fromJson(Map<String, dynamic> json) => LineElement(
        checked: json["checked"],
        endState: endStateValues.map[json["end_state"]],
        note: json["note"],
        state: lineStateValues.map[json["state"]]!,
        taskId: json["task_id"],
        text: json["text"],
        when: json["when"] == null ? null : LineWhen.fromJson(json["when"]),
    );

    Map<String, dynamic> toJson() => {
        "checked": checked,
        "end_state": endStateValues.reverse[endState],
        "note": note,
        "state": lineStateValues.reverse[state],
        "task_id": taskId,
        "text": text,
        "when": when?.toJson(),
    };
}

enum EndState {
    KEPT_USER_CHANGE,
    NONE,
    RESTORED,
    RESTORE_FAILED
}

final endStateValues = EnumValues({
    "kept_user_change": EndState.KEPT_USER_CHANGE,
    "none": EndState.NONE,
    "restored": EndState.RESTORED,
    "restore_failed": EndState.RESTORE_FAILED
});

enum LineState {
    BLOCKED,
    CANCELLED,
    DONE,
    DROPPED,
    FAILED,
    HELD,
    OFF,
    PARTIAL,
    RUNNING,
    SCHEDULED,
    STOPPED,
    UNKNOWN,
    USER_CHANGED
}

final lineStateValues = EnumValues({
    "blocked": LineState.BLOCKED,
    "cancelled": LineState.CANCELLED,
    "done": LineState.DONE,
    "dropped": LineState.DROPPED,
    "failed": LineState.FAILED,
    "held": LineState.HELD,
    "off": LineState.OFF,
    "partial": LineState.PARTIAL,
    "running": LineState.RUNNING,
    "scheduled": LineState.SCHEDULED,
    "stopped": LineState.STOPPED,
    "unknown": LineState.UNKNOWN,
    "user_changed": LineState.USER_CHANGED
});

class LineWhen {
    final String? time;
    final TriggerEvent? event;

    LineWhen({
        this.time,
        this.event,
    });

    factory LineWhen.fromJson(Map<String, dynamic> json) => LineWhen(
        time: json["time"],
        event: triggerEventValues.map[json["event"]],
    );

    Map<String, dynamic> toJson() => {
        "time": time,
        "event": triggerEventValues.reverse[event],
    };
}

enum TriggerEvent {
    EVENT_END,
    GUEST_ARRIVED,
    PACKAGE_BROUGHT_IN
}

final triggerEventValues = EnumValues({
    "event_end": TriggerEvent.EVENT_END,
    "guest_arrived": TriggerEvent.GUEST_ARRIVED,
    "package.brought_in": TriggerEvent.PACKAGE_BROUGHT_IN
});

class Summary {
    final int done;
    final int total;
    final TriggerEvent? waitingFor;

    Summary({
        required this.done,
        required this.total,
        required this.waitingFor,
    });

    factory Summary.fromJson(Map<String, dynamic> json) => Summary(
        done: json["done"],
        total: json["total"],
        waitingFor: triggerEventValues.map[json["waiting_for"]],
    );

    Map<String, dynamic> toJson() => {
        "done": done,
        "total": total,
        "waiting_for": triggerEventValues.reverse[waitingFor],
    };
}


///One row of the cases table (C-5). synthetic rows: written by SPIRA_KB. this_home rows:
///written by the server, one per card (intent). Columns match
///server/migrations/versions/0001_create_cases.py. (KB-05, KB-06)
class CaseRow {
    
    ///BGE-M3 via spira.embedding.embed_basket (KB-16). Omitted in fixtures.
    final List<double>? basketEmb;
    final String caseId;
    final List<HomeDidElement>? homeDid;
    final Household household;
    final String? householdId;
    final String intentId;
    final String? intentText;
    
    ///Plain item names of the whole order, sorted (가나다), masked items excluded, no quantities.
    final List<String> items;
    
    ///synthetic: first KB version the case entered. this_home: null.
    final String? kbVersion;
    final Situation situation;
    final CaseSource source;
    final List<TaskFeedbackElement>? taskFeedback;
    final Verdict? verdict;
    final CaseRowWhen when;

    CaseRow({
        this.basketEmb,
        required this.caseId,
        this.homeDid,
        required this.household,
        this.householdId,
        required this.intentId,
        required this.intentText,
        required this.items,
        required this.kbVersion,
        required this.situation,
        required this.source,
        this.taskFeedback,
        this.verdict,
        required this.when,
    });

    factory CaseRow.fromJson(Map<String, dynamic> json) => CaseRow(
        basketEmb: json["basket_emb"] == null ? [] : List<double>.from(json["basket_emb"]!.map((x) => x?.toDouble())),
        caseId: json["case_id"],
        homeDid: json["home_did"] == null ? [] : List<HomeDidElement>.from(json["home_did"]!.map((x) => HomeDidElement.fromJson(x))),
        household: Household.fromJson(json["household"]),
        householdId: json["household_id"],
        intentId: json["intent_id"],
        intentText: json["intent_text"],
        items: List<String>.from(json["items"].map((x) => x)),
        kbVersion: json["kb_version"],
        situation: Situation.fromJson(json["situation"]),
        source: caseSourceValues.map[json["source"]]!,
        taskFeedback: json["task_feedback"] == null ? [] : List<TaskFeedbackElement>.from(json["task_feedback"]!.map((x) => TaskFeedbackElement.fromJson(x))),
        verdict: verdictValues.map[json["verdict"]],
        when: CaseRowWhen.fromJson(json["when"]),
    );

    Map<String, dynamic> toJson() => {
        "basket_emb": basketEmb == null ? [] : List<dynamic>.from(basketEmb!.map((x) => x)),
        "case_id": caseId,
        "home_did": homeDid == null ? [] : List<dynamic>.from(homeDid!.map((x) => x.toJson())),
        "household": household.toJson(),
        "household_id": householdId,
        "intent_id": intentId,
        "intent_text": intentText,
        "items": List<dynamic>.from(items.map((x) => x)),
        "kb_version": kbVersion,
        "situation": situation.toJson(),
        "source": caseSourceValues.reverse[source],
        "task_feedback": taskFeedback == null ? [] : List<dynamic>.from(taskFeedback!.map((x) => x.toJson())),
        "verdict": verdictValues.reverse[verdict],
        "when": when.toJson(),
    };
}

class HomeDidElement {
    final List<List<String>> actions;
    final String line;
    final bool ran;
    final String taskId;
    final Way way;

    HomeDidElement({
        required this.actions,
        required this.line,
        required this.ran,
        required this.taskId,
        required this.way,
    });

    factory HomeDidElement.fromJson(Map<String, dynamic> json) => HomeDidElement(
        actions: List<List<String>>.from(json["actions"].map((x) => List<String>.from(x.map((x) => x)))),
        line: json["line"],
        ran: json["ran"],
        taskId: json["task_id"],
        way: wayValues.map[json["way"]]!,
    );

    Map<String, dynamic> toJson() => {
        "actions": List<dynamic>.from(actions.map((x) => List<dynamic>.from(x.map((x) => x)))),
        "line": line,
        "ran": ran,
        "task_id": taskId,
        "way": wayValues.reverse[way],
    };
}

enum Way {
    NOTICE,
    RUN,
    STANDBY
}

final wayValues = EnumValues({
    "notice": Way.NOTICE,
    "run": Way.RUN,
    "standby": Way.STANDBY
});

class Household {
    final List<String>? types;

    Household({
        required this.types,
    });

    factory Household.fromJson(Map<String, dynamic> json) => Household(
        types: json["types"] == null ? [] : List<String>.from(json["types"]!.map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "types": types == null ? [] : List<dynamic>.from(types!.map((x) => x)),
    };
}

class Situation {
    final String? activity;
    final String? event;
    final String? guests;
    final String? theme;

    Situation({
        required this.activity,
        required this.event,
        required this.guests,
        required this.theme,
    });

    factory Situation.fromJson(Map<String, dynamic> json) => Situation(
        activity: json["activity"],
        event: json["event"],
        guests: json["guests"],
        theme: json["theme"],
    );

    Map<String, dynamic> toJson() => {
        "activity": activity,
        "event": event,
        "guests": guests,
        "theme": theme,
    };
}

enum CaseSource {
    OTHER_HOME,
    SYNTHETIC,
    THIS_HOME
}

final caseSourceValues = EnumValues({
    "other_home": CaseSource.OTHER_HOME,
    "synthetic": CaseSource.SYNTHETIC,
    "this_home": CaseSource.THIS_HOME
});


///Final state of one card line when the observation window closed.
class TaskFeedbackElement {
    final List<List<String>> actions;
    
    ///off only: the day it was switched off.
    final String? at;
    
    ///changed only.
    final List<Change>? changes;
    final String taskId;
    final TaskFeedback user;
    
    ///off only.
    final OffWhen? when;

    TaskFeedbackElement({
        required this.actions,
        this.at,
        this.changes,
        required this.taskId,
        required this.user,
        this.when,
    });

    factory TaskFeedbackElement.fromJson(Map<String, dynamic> json) => TaskFeedbackElement(
        actions: List<List<String>>.from(json["actions"].map((x) => List<String>.from(x.map((x) => x)))),
        at: json["at"],
        changes: json["changes"] == null ? [] : List<Change>.from(json["changes"]!.map((x) => Change.fromJson(x))),
        taskId: json["task_id"],
        user: taskFeedbackValues.map[json["user"]]!,
        when: offWhenValues.map[json["when"]],
    );

    Map<String, dynamic> toJson() => {
        "actions": List<dynamic>.from(actions.map((x) => List<dynamic>.from(x.map((x) => x)))),
        "at": at,
        "changes": changes == null ? [] : List<dynamic>.from(changes!.map((x) => x.toJson())),
        "task_id": taskId,
        "user": taskFeedbackValues.reverse[user],
        "when": offWhenValues.reverse[when],
    };
}

class Change {
    
    ///Minutes after the schedule start.
    final int afterStartMinutes;
    final String deviceType;
    final String property;
    
    ///Value the person set, e.g. {"kelvin": 2700}.
    final dynamic to;

    Change({
        required this.afterStartMinutes,
        required this.deviceType,
        required this.property,
        required this.to,
    });

    factory Change.fromJson(Map<String, dynamic> json) => Change(
        afterStartMinutes: json["after_start_minutes"],
        deviceType: json["device_type"],
        property: json["property"],
        to: json["to"],
    );

    Map<String, dynamic> toJson() => {
        "after_start_minutes": afterStartMinutes,
        "device_type": deviceType,
        "property": property,
        "to": to,
    };
}

enum TaskFeedback {
    CHANGED,
    KEPT,
    OFF
}

final taskFeedbackValues = EnumValues({
    "changed": TaskFeedback.CHANGED,
    "kept": TaskFeedback.KEPT,
    "off": TaskFeedback.OFF
});


///off only.
enum OffWhen {
    BEFORE_RUN,
    DURING_RUN
}

final offWhenValues = EnumValues({
    "before_run": OffWhen.BEFORE_RUN,
    "during_run": OffWhen.DURING_RUN
});

enum Verdict {
    MATCH,
    STOPPED,
    UNCONFIRMED
}

final verdictValues = EnumValues({
    "match": Verdict.MATCH,
    "stopped": Verdict.STOPPED,
    "unconfirmed": Verdict.UNCONFIRMED
});

class CaseRowWhen {
    final List<String> calendarTags;
    
    ///this_home only: first preparation run.
    final String? executedAt;
    
    ///synthetic: arrival weekday. this_home: weekday of executed_at.
    final Weekday weekday;

    CaseRowWhen({
        required this.calendarTags,
        this.executedAt,
        required this.weekday,
    });

    factory CaseRowWhen.fromJson(Map<String, dynamic> json) => CaseRowWhen(
        calendarTags: List<String>.from(json["calendar_tags"].map((x) => x)),
        executedAt: json["executed_at"],
        weekday: weekdayValues.map[json["weekday"]]!,
    );

    Map<String, dynamic> toJson() => {
        "calendar_tags": List<dynamic>.from(calendarTags.map((x) => x)),
        "executed_at": executedAt,
        "weekday": weekdayValues.reverse[weekday],
    };
}


///synthetic: arrival weekday. this_home: weekday of executed_at.
enum Weekday {
    EMPTY,
    FLUFFY,
    INDIGO,
    PURPLE,
    STICKY,
    TENTACLED,
    WEEKDAY
}

final weekdayValues = EnumValues({
    "월": Weekday.EMPTY,
    "목": Weekday.FLUFFY,
    "일": Weekday.INDIGO,
    "수": Weekday.PURPLE,
    "토": Weekday.STICKY,
    "금": Weekday.TENTACLED,
    "화": Weekday.WEEKDAY
});


///Devices the household delegated to SPIRA (C-2). Hub -> server: PUT
////v1/hub/households/{hid}/devices at start and whenever devices, rooms or delegation
///change (revision + 1). (HUB-05, HUB-06, HUB-11)
class Devices {
    final List<DeviceElement> devices;
    final String householdId;
    final int revision;
    final String updatedAt;

    Devices({
        required this.devices,
        required this.householdId,
        required this.revision,
        required this.updatedAt,
    });

    factory Devices.fromJson(Map<String, dynamic> json) => Devices(
        devices: List<DeviceElement>.from(json["devices"].map((x) => DeviceElement.fromJson(x))),
        householdId: json["household_id"],
        revision: json["revision"],
        updatedAt: json["updated_at"],
    );

    Map<String, dynamic> toJson() => {
        "devices": List<dynamic>.from(devices.map((x) => x.toJson())),
        "household_id": householdId,
        "revision": revision,
        "updated_at": updatedAt,
    };
}

class DeviceElement {
    
    ///Delegated commands. The server plans only with these.
    final List<CommandElement> commands;
    final List<String> events;
    final String id;
    
    ///What a smart plug powers (e.g. 전기포트).
    final String? label;
    
    ///Commands not delegated (e.g. oven start).
    final List<String> never;
    
    ///Noisy devices are not run 22:00-08:00.
    final bool noisy;
    
    ///Room name as the user wrote it (e.g. 거실). null = unknown.
    final String? room;
    final Substrate substrate;
    final String type;

    DeviceElement({
        required this.commands,
        required this.events,
        required this.id,
        this.label,
        required this.never,
        required this.noisy,
        required this.room,
        required this.substrate,
        required this.type,
    });

    factory DeviceElement.fromJson(Map<String, dynamic> json) => DeviceElement(
        commands: List<CommandElement>.from(json["commands"].map((x) => CommandElement.fromJson(x))),
        events: List<String>.from(json["events"].map((x) => x)),
        id: json["id"],
        label: json["label"],
        never: List<String>.from(json["never"].map((x) => x)),
        noisy: json["noisy"],
        room: json["room"],
        substrate: substrateValues.map[json["substrate"]]!,
        type: json["type"],
    );

    Map<String, dynamic> toJson() => {
        "commands": List<dynamic>.from(commands.map((x) => x.toJson())),
        "events": List<dynamic>.from(events.map((x) => x)),
        "id": id,
        "label": label,
        "never": List<dynamic>.from(never.map((x) => x)),
        "noisy": noisy,
        "room": room,
        "substrate": substrateValues.reverse[substrate],
        "type": type,
    };
}

class CommandElement {
    final String cmd;
    
    ///Absent = the command takes no value. 'text' = free text (show_notice only). Otherwise one
    ///entry per parameter; the server fills every parameter.
    final dynamic valueSchema;

    CommandElement({
        required this.cmd,
        this.valueSchema,
    });

    factory CommandElement.fromJson(Map<String, dynamic> json) => CommandElement(
        cmd: json["cmd"],
        valueSchema: json["value_schema"],
    );

    Map<String, dynamic> toJson() => {
        "cmd": cmd,
        "value_schema": valueSchema,
    };
}

enum ValueSchemaEnum {
    TEXT
}

final valueSchemaEnumValues = EnumValues({
    "text": ValueSchemaEnum.TEXT
});

class ValueSchemaValue {
    final dynamic devicesDefault;
    final List<double>? range;
    final List<String>? devicesEnum;

    ValueSchemaValue({
        required this.devicesDefault,
        this.range,
        this.devicesEnum,
    });

    factory ValueSchemaValue.fromJson(Map<String, dynamic> json) => ValueSchemaValue(
        devicesDefault: json["default"],
        range: json["range"] == null ? [] : List<double>.from(json["range"]!.map((x) => x?.toDouble())),
        devicesEnum: json["enum"] == null ? [] : List<String>.from(json["enum"]!.map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "default": devicesDefault,
        "range": range == null ? [] : List<dynamic>.from(range!.map((x) => x)),
        "enum": devicesEnum == null ? [] : List<dynamic>.from(devicesEnum!.map((x) => x)),
    };
}

enum Substrate {
    PHYSICAL,
    VIRTUAL
}

final substrateValues = EnumValues({
    "physical": Substrate.PHYSICAL,
    "virtual": Substrate.VIRTUAL
});


///Response of PUT /v1/hub/households/{hid}/devices: the revision the server stored. (HUB-05)
class DevicesResponse {
    final int revision;

    DevicesResponse({
        required this.revision,
    });

    factory DevicesResponse.fromJson(Map<String, dynamic> json) => DevicesResponse(
        revision: json["revision"],
    );

    Map<String, dynamic> toJson() => {
        "revision": revision,
    };
}


///One shared order (all captures within 8 h). Server -> app: GET /v1/episodes/{id}. items
///feed the order edit screen; masked items appear only as masked_count. (APP-07, APP-11)
class Episode {
    final List<String> cardIds;
    final String episodeId;
    final String householdId;
    
    ///Items read, masked included.
    final int itemCount;
    
    ///Per-item tasks (care notices etc.). Not on the card.
    final List<ItemTaskElement> itemTasks;
    final List<EpisodeItem> items;
    final int maskedCount;
    
    ///First capture.
    final String sharedAt;
    final EpisodeStatus status;

    Episode({
        required this.cardIds,
        required this.episodeId,
        required this.householdId,
        required this.itemCount,
        required this.itemTasks,
        required this.items,
        required this.maskedCount,
        required this.sharedAt,
        required this.status,
    });

    factory Episode.fromJson(Map<String, dynamic> json) => Episode(
        cardIds: List<String>.from(json["card_ids"].map((x) => x)),
        episodeId: json["episode_id"],
        householdId: json["household_id"],
        itemCount: json["item_count"],
        itemTasks: List<ItemTaskElement>.from(json["item_tasks"].map((x) => ItemTaskElement.fromJson(x))),
        items: List<EpisodeItem>.from(json["items"].map((x) => EpisodeItem.fromJson(x))),
        maskedCount: json["masked_count"],
        sharedAt: json["shared_at"],
        status: episodeStatusValues.map[json["status"]]!,
    );

    Map<String, dynamic> toJson() => {
        "card_ids": List<dynamic>.from(cardIds.map((x) => x)),
        "episode_id": episodeId,
        "household_id": householdId,
        "item_count": itemCount,
        "item_tasks": List<dynamic>.from(itemTasks.map((x) => x.toJson())),
        "items": List<dynamic>.from(items.map((x) => x.toJson())),
        "masked_count": maskedCount,
        "shared_at": sharedAt,
        "status": episodeStatusValues.reverse[status],
    };
}

class ItemTaskElement {
    final String item;
    final NoticeKind? kind;
    final LineState state;
    final String taskId;
    final String? text;

    ItemTaskElement({
        required this.item,
        required this.kind,
        required this.state,
        required this.taskId,
        required this.text,
    });

    factory ItemTaskElement.fromJson(Map<String, dynamic> json) => ItemTaskElement(
        item: json["item"],
        kind: noticeKindValues.map[json["kind"]],
        state: lineStateValues.map[json["state"]]!,
        taskId: json["task_id"],
        text: json["text"],
    );

    Map<String, dynamic> toJson() => {
        "item": item,
        "kind": noticeKindValues.reverse[kind],
        "state": lineStateValues.reverse[state],
        "task_id": taskId,
        "text": text,
    };
}

enum NoticeKind {
    PREP,
    STORAGE
}

final noticeKindValues = EnumValues({
    "prep": NoticeKind.PREP,
    "storage": NoticeKind.STORAGE
});

class EpisodeItem {
    final String itemId;
    
    ///Product name as shown.
    final String name;
    final int? qty;
    
    ///Plain item name (e.g. 딸기).
    final String type;

    EpisodeItem({
        required this.itemId,
        required this.name,
        required this.qty,
        required this.type,
    });

    factory EpisodeItem.fromJson(Map<String, dynamic> json) => EpisodeItem(
        itemId: json["item_id"],
        name: json["name"],
        qty: json["qty"],
        type: json["type"],
    );

    Map<String, dynamic> toJson() => {
        "item_id": itemId,
        "name": name,
        "qty": qty,
        "type": type,
    };
}

enum EpisodeStatus {
    CLOSED,
    HELD,
    JUDGED,
    NOTIFIED,
    PAUSED_SKIP,
    READING,
    READ_FAILED,
    RECEIVED
}

final episodeStatusValues = EnumValues({
    "closed": EpisodeStatus.CLOSED,
    "held": EpisodeStatus.HELD,
    "judged": EpisodeStatus.JUDGED,
    "notified": EpisodeStatus.NOTIFIED,
    "paused_skip": EpisodeStatus.PAUSED_SKIP,
    "reading": EpisodeStatus.READING,
    "read_failed": EpisodeStatus.READ_FAILED,
    "received": EpisodeStatus.RECEIVED
});


///Response of GET /v1/households/{hid}/episodes?limit=&before= (newest first). Pass
///next_before to get older ones. (APP-01)
class EpisodeList {
    final List<EpisodeListEpisode> episodes;
    final String? nextBefore;

    EpisodeList({
        required this.episodes,
        required this.nextBefore,
    });

    factory EpisodeList.fromJson(Map<String, dynamic> json) => EpisodeList(
        episodes: List<EpisodeListEpisode>.from(json["episodes"].map((x) => EpisodeListEpisode.fromJson(x))),
        nextBefore: json["next_before"],
    );

    Map<String, dynamic> toJson() => {
        "episodes": List<dynamic>.from(episodes.map((x) => x.toJson())),
        "next_before": nextBefore,
    };
}

class EpisodeListEpisode {
    final List<String> cardIds;
    final String episodeId;
    final int itemCount;
    final String sharedAt;
    final EpisodeStatus status;

    EpisodeListEpisode({
        required this.cardIds,
        required this.episodeId,
        required this.itemCount,
        required this.sharedAt,
        required this.status,
    });

    factory EpisodeListEpisode.fromJson(Map<String, dynamic> json) => EpisodeListEpisode(
        cardIds: List<String>.from(json["card_ids"].map((x) => x)),
        episodeId: json["episode_id"],
        itemCount: json["item_count"],
        sharedAt: json["shared_at"],
        status: episodeStatusValues.map[json["status"]]!,
    );

    Map<String, dynamic> toJson() => {
        "card_ids": List<dynamic>.from(cardIds.map((x) => x)),
        "episode_id": episodeId,
        "item_count": itemCount,
        "shared_at": sharedAt,
        "status": episodeStatusValues.reverse[status],
    };
}


///Body of every 4xx / 5xx response. (COM-05)
class Error {
    final ErrorCode code;
    
    ///validation_error: {"path": "tasks[0].way", "reason": "..."}.
    final Map<String, dynamic>? details;
    final String message;

    Error({
        required this.code,
        this.details,
        required this.message,
    });

    factory Error.fromJson(Map<String, dynamic> json) => Error(
        code: errorCodeValues.map[json["code"]]!,
        details: Map.from(json["details"]!).map((k, v) => MapEntry<String, dynamic>(k, v)),
        message: json["message"],
    );

    Map<String, dynamic> toJson() => {
        "code": errorCodeValues.reverse[code],
        "details": Map.from(details!).map((k, v) => MapEntry<String, dynamic>(k, v)),
        "message": message,
    };
}

enum ErrorCode {
    FORBIDDEN,
    HOUSEHOLD_TYPES_INVALID,
    INTERNAL,
    INVALID_IMAGE,
    INVALID_REQUEST,
    LINE_STARTED,
    NOT_FOUND,
    STALE_REVISION,
    UNAUTHORIZED,
    VALIDATION_ERROR
}

final errorCodeValues = EnumValues({
    "forbidden": ErrorCode.FORBIDDEN,
    "household_types_invalid": ErrorCode.HOUSEHOLD_TYPES_INVALID,
    "internal": ErrorCode.INTERNAL,
    "invalid_image": ErrorCode.INVALID_IMAGE,
    "invalid_request": ErrorCode.INVALID_REQUEST,
    "line_started": ErrorCode.LINE_STARTED,
    "not_found": ErrorCode.NOT_FOUND,
    "stale_revision": ErrorCode.STALE_REVISION,
    "unauthorized": ErrorCode.UNAUTHORIZED,
    "validation_error": ErrorCode.VALIDATION_ERROR
});


///A home event or device event (C-3). Hub -> server inside POST /v1/hub/events. Device
///events carry payload.by; '{type}.changed' also carries property / from / to. (HUB-07)
///
///Request body of POST /v1/hub/events: one or more events in time order. (HUB-07)
class EventBatch {
    final String at;
    final String eventId;
    final String householdId;
    
    ///Event details. Other keys are allowed (e.g. rule of guest_arrived) and are stored, not
    ///interpreted.
    final Payload payload;
    
    ///'hub' for home events, otherwise the device id.
    final String source;
    final String type;

    EventBatch({
        required this.at,
        required this.eventId,
        required this.householdId,
        required this.payload,
        required this.source,
        required this.type,
    });

    factory EventBatch.fromJson(Map<String, dynamic> json) => EventBatch(
        at: json["at"],
        eventId: json["event_id"],
        householdId: json["household_id"],
        payload: Payload.fromJson(json["payload"]),
        source: json["source"],
        type: json["type"],
    );

    Map<String, dynamic> toJson() => {
        "at": at,
        "event_id": eventId,
        "household_id": householdId,
        "payload": payload.toJson(),
        "source": source,
        "type": type,
    };
}


///Event details. Other keys are allowed (e.g. rule of guest_arrived) and are stored, not
///interpreted.
class Payload {
    final By? by;
    
    ///package.brought_in: number of packages.
    final int? count;
    
    ///Value before (object or null).
    final dynamic from;
    
    ///Changed command / property, e.g. color_temp.
    final String? property;
    
    ///guest_arrived / event_end: how the hub decided (display text).
    final String? rule;
    
    ///Value after.
    final dynamic to;

    Payload({
        this.by,
        this.count,
        this.from,
        this.property,
        this.rule,
        this.to,
    });

    factory Payload.fromJson(Map<String, dynamic> json) => Payload(
        by: byValues.map[json["by"]],
        count: json["count"],
        from: json["from"],
        property: json["property"],
        rule: json["rule"],
        to: json["to"],
    );

    Map<String, dynamic> toJson() => {
        "by": byValues.reverse[by],
        "count": count,
        "from": from,
        "property": property,
        "rule": rule,
        "to": to,
    };
}


///Only an end event caused by this actor counts.
enum By {
    SPIRA,
    UNKNOWN,
    USER
}

final byValues = EnumValues({
    "spira": By.SPIRA,
    "unknown": By.UNKNOWN,
    "user": By.USER
});


///Response of POST /v1/hub/events. Duplicates count as accepted. plans_changed = pull now.
///(HUB-04, HUB-07)
class EventResponse {
    final List<String> accepted;
    final bool plansChanged;
    
    ///Events not stored (bad shape, unknown device). Fix and resend with the same event_id.
    final List<Rejected> rejected;

    EventResponse({
        required this.accepted,
        required this.plansChanged,
        required this.rejected,
    });

    factory EventResponse.fromJson(Map<String, dynamic> json) => EventResponse(
        accepted: List<String>.from(json["accepted"].map((x) => x)),
        plansChanged: json["plans_changed"],
        rejected: List<Rejected>.from(json["rejected"].map((x) => Rejected.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "accepted": List<dynamic>.from(accepted.map((x) => x)),
        "plans_changed": plansChanged,
        "rejected": List<dynamic>.from(rejected.map((x) => x.toJson())),
    };
}

class Rejected {
    final ErrorCode code;
    final String eventId;
    final String message;

    Rejected({
        required this.code,
        required this.eventId,
        required this.message,
    });

    factory Rejected.fromJson(Map<String, dynamic> json) => Rejected(
        code: errorCodeValues.map[json["code"]]!,
        eventId: json["event_id"],
        message: json["message"],
    );

    Map<String, dynamic> toJson() => {
        "code": errorCodeValues.reverse[code],
        "event_id": eventId,
        "message": message,
    };
}


///Response of POST /v1/hub/executions. duplicate = this result_id was already stored
///(nothing changed). (COM-04)
class ExecutionResponse {
    final bool duplicate;

    ExecutionResponse({
        required this.duplicate,
    });

    factory ExecutionResponse.fromJson(Map<String, dynamic> json) => ExecutionResponse(
        duplicate: json["duplicate"],
    );

    Map<String, dynamic> toJson() => {
        "duplicate": duplicate,
    };
}


///Result of one action (one device) or of one restore (C-4). Hub -> server: POST
////v1/hub/executions, one result per request. completed needs a fresh read-back, not just
///an ACK. (HUB-08)
class ExecutionResult {
    final String at;
    final String? cmd;
    final String? device;
    final Kind kind;
    
    ///State read back after the action.
    final Map<String, dynamic>? observed;
    
    ///Same for every result of one dispatch (e.g. running then completed).
    final String? operationId;
    final String planId;
    final int planVersion;
    
    ///Required (non-null) when status is blocked.
    final BlockedReason? reason;
    final String resultId;
    
    ///State before the action, used for restore.
    final Map<String, dynamic>? savedState;
    final ExecutionStatus? status;
    final Substrate? substrate;
    final String taskId;
    final List<ExecutionResultItem>? items;

    ExecutionResult({
        required this.at,
        this.cmd,
        this.device,
        required this.kind,
        this.observed,
        this.operationId,
        required this.planId,
        required this.planVersion,
        this.reason,
        required this.resultId,
        this.savedState,
        this.status,
        this.substrate,
        required this.taskId,
        this.items,
    });

    factory ExecutionResult.fromJson(Map<String, dynamic> json) => ExecutionResult(
        at: json["at"],
        cmd: json["cmd"],
        device: json["device"],
        kind: kindValues.map[json["kind"]]!,
        observed: Map.from(json["observed"]!).map((k, v) => MapEntry<String, dynamic>(k, v)),
        operationId: json["operation_id"],
        planId: json["plan_id"],
        planVersion: json["plan_version"],
        reason: blockedReasonValues.map[json["reason"]],
        resultId: json["result_id"],
        savedState: Map.from(json["saved_state"]!).map((k, v) => MapEntry<String, dynamic>(k, v)),
        status: executionStatusValues.map[json["status"]],
        substrate: substrateValues.map[json["substrate"]],
        taskId: json["task_id"],
        items: json["items"] == null ? [] : List<ExecutionResultItem>.from(json["items"]!.map((x) => ExecutionResultItem.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "at": at,
        "cmd": cmd,
        "device": device,
        "kind": kindValues.reverse[kind],
        "observed": Map.from(observed!).map((k, v) => MapEntry<String, dynamic>(k, v)),
        "operation_id": operationId,
        "plan_id": planId,
        "plan_version": planVersion,
        "reason": blockedReasonValues.reverse[reason],
        "result_id": resultId,
        "saved_state": Map.from(savedState!).map((k, v) => MapEntry<String, dynamic>(k, v)),
        "status": executionStatusValues.reverse[status],
        "substrate": substrateValues.reverse[substrate],
        "task_id": taskId,
        "items": items == null ? [] : List<dynamic>.from(items!.map((x) => x.toJson())),
    };
}

class ExecutionResultItem {
    final String device;
    final RestoreItemStatus status;

    ExecutionResultItem({
        required this.device,
        required this.status,
    });

    factory ExecutionResultItem.fromJson(Map<String, dynamic> json) => ExecutionResultItem(
        device: json["device"],
        status: restoreItemStatusValues.map[json["status"]]!,
    );

    Map<String, dynamic> toJson() => {
        "device": device,
        "status": restoreItemStatusValues.reverse[status],
    };
}

enum RestoreItemStatus {
    FAILED,
    NOT_NEEDED,
    RESTORED,
    SKIPPED_USER_CHANGED,
    UNKNOWN
}

final restoreItemStatusValues = EnumValues({
    "failed": RestoreItemStatus.FAILED,
    "not_needed": RestoreItemStatus.NOT_NEEDED,
    "restored": RestoreItemStatus.RESTORED,
    "skipped_user_changed": RestoreItemStatus.SKIPPED_USER_CHANGED,
    "unknown": RestoreItemStatus.UNKNOWN
});

enum Kind {
    RESTORE,
    RUN
}

final kindValues = EnumValues({
    "restore": Kind.RESTORE,
    "run": Kind.RUN
});

enum BlockedReason {
    ALREADY_DONE_BY_PERSON,
    IN_USE_BY_PERSON,
    NOT_DELEGATED,
    OFFLINE,
    PAUSED,
    PLAN_CANCELLED,
    PLAN_UNCONFIRMED,
    QUIET_HOURS
}

final blockedReasonValues = EnumValues({
    "already_done_by_person": BlockedReason.ALREADY_DONE_BY_PERSON,
    "in_use_by_person": BlockedReason.IN_USE_BY_PERSON,
    "not_delegated": BlockedReason.NOT_DELEGATED,
    "offline": BlockedReason.OFFLINE,
    "paused": BlockedReason.PAUSED,
    "plan_cancelled": BlockedReason.PLAN_CANCELLED,
    "plan_unconfirmed": BlockedReason.PLAN_UNCONFIRMED,
    "quiet_hours": BlockedReason.QUIET_HOURS
});

enum ExecutionStatus {
    BLOCKED,
    COMPLETED,
    FAILED,
    RUNNING,
    UNKNOWN,
    UNVERIFIABLE
}

final executionStatusValues = EnumValues({
    "blocked": ExecutionStatus.BLOCKED,
    "completed": ExecutionStatus.COMPLETED,
    "failed": ExecutionStatus.FAILED,
    "running": ExecutionStatus.RUNNING,
    "unknown": ExecutionStatus.UNKNOWN,
    "unverifiable": ExecutionStatus.UNVERIFIABLE
});


///Response of GET /health (no auth). 200 when ready, 503 otherwise. (COM-08)
class Health {
    final bool? db;
    final bool? embedding;
    final Status status;

    Health({
        this.db,
        this.embedding,
        required this.status,
    });

    factory Health.fromJson(Map<String, dynamic> json) => Health(
        db: json["db"],
        embedding: json["embedding"],
        status: statusValues.map[json["status"]]!,
    );

    Map<String, dynamic> toJson() => {
        "db": db,
        "embedding": embedding,
        "status": statusValues.reverse[status],
    };
}

enum Status {
    DEGRADED,
    OK
}

final statusValues = EnumValues({
    "degraded": Status.DEGRADED,
    "ok": Status.OK
});


///App -> server: POST /v1/households (onboarding). household_types may be empty and set
///later via profile. (HUB-14, APP-12)
class HouseholdCreate {
    
    ///Values from kb/household_types.json.
    final List<String> householdTypes;

    HouseholdCreate({
        required this.householdTypes,
    });

    factory HouseholdCreate.fromJson(Map<String, dynamic> json) => HouseholdCreate(
        householdTypes: List<String>.from(json["household_types"].map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "household_types": List<dynamic>.from(householdTypes.map((x) => x)),
    };
}


///Response 201 of POST /v1/households. The app passes hub_api_key once to the hub's local
///setup route; it is never shown again. (HUB-14)
class HouseholdCreated {
    final String householdId;
    final String hubApiKey;

    HouseholdCreated({
        required this.householdId,
        required this.hubApiKey,
    });

    factory HouseholdCreated.fromJson(Map<String, dynamic> json) => HouseholdCreated(
        householdId: json["household_id"],
        hubApiKey: json["hub_api_key"],
    );

    Map<String, dynamic> toJson() => {
        "household_id": householdId,
        "hub_api_key": hubApiKey,
    };
}


///This home's memory grouped by intent (intent id + calendar tags). Server -> app: GET
////v1/households/{hid}/memory; delete one case with DELETE .../memory/{case_id}. (APP-15)
class Memory {
    final String householdId;
    final List<Intent> intents;

    Memory({
        required this.householdId,
        required this.intents,
    });

    factory Memory.fromJson(Map<String, dynamic> json) => Memory(
        householdId: json["household_id"],
        intents: List<Intent>.from(json["intents"].map((x) => Intent.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "household_id": householdId,
        "intents": List<dynamic>.from(intents.map((x) => x.toJson())),
    };
}

class Intent {
    final List<String> calendarTags;
    final List<Changed> changed;
    final List<IntentEpisode> episodes;
    final HabitTime? habitTime;
    final String intentId;
    final String name;
    final List<OffLine> offLines;

    Intent({
        required this.calendarTags,
        required this.changed,
        required this.episodes,
        required this.habitTime,
        required this.intentId,
        required this.name,
        required this.offLines,
    });

    factory Intent.fromJson(Map<String, dynamic> json) => Intent(
        calendarTags: List<String>.from(json["calendar_tags"].map((x) => x)),
        changed: List<Changed>.from(json["changed"].map((x) => Changed.fromJson(x))),
        episodes: List<IntentEpisode>.from(json["episodes"].map((x) => IntentEpisode.fromJson(x))),
        habitTime: json["habit_time"] == null ? null : HabitTime.fromJson(json["habit_time"]),
        intentId: json["intent_id"],
        name: json["name"],
        offLines: List<OffLine>.from(json["off_lines"].map((x) => OffLine.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "calendar_tags": List<dynamic>.from(calendarTags.map((x) => x)),
        "changed": List<dynamic>.from(changed.map((x) => x.toJson())),
        "episodes": List<dynamic>.from(episodes.map((x) => x.toJson())),
        "habit_time": habitTime?.toJson(),
        "intent_id": intentId,
        "name": name,
        "off_lines": List<dynamic>.from(offLines.map((x) => x.toJson())),
    };
}

class Changed {
    final String caseId;
    
    ///Display text.
    final String change;
    final String deviceType;

    Changed({
        required this.caseId,
        required this.change,
        required this.deviceType,
    });

    factory Changed.fromJson(Map<String, dynamic> json) => Changed(
        caseId: json["case_id"],
        change: json["change"],
        deviceType: json["device_type"],
    );

    Map<String, dynamic> toJson() => {
        "case_id": caseId,
        "change": change,
        "device_type": deviceType,
    };
}

class IntentEpisode {
    final String caseId;
    final String date;
    final Verdict verdict;

    IntentEpisode({
        required this.caseId,
        required this.date,
        required this.verdict,
    });

    factory IntentEpisode.fromJson(Map<String, dynamic> json) => IntentEpisode(
        caseId: json["case_id"],
        date: json["date"],
        verdict: verdictValues.map[json["verdict"]]!,
    );

    Map<String, dynamic> toJson() => {
        "case_id": caseId,
        "date": date,
        "verdict": verdictValues.reverse[verdict],
    };
}

class HabitTime {
    final String time;
    final String weekday;

    HabitTime({
        required this.time,
        required this.weekday,
    });

    factory HabitTime.fromJson(Map<String, dynamic> json) => HabitTime(
        time: json["time"],
        weekday: json["weekday"],
    );

    Map<String, dynamic> toJson() => {
        "time": time,
        "weekday": weekday,
    };
}

class OffLine {
    final String caseId;
    final String line;
    
    ///Left out of new plans until this day (180 days).
    final String until;

    OffLine({
        required this.caseId,
        required this.line,
        required this.until,
    });

    factory OffLine.fromJson(Map<String, dynamic> json) => OffLine(
        caseId: json["case_id"],
        line: json["line"],
        until: json["until"],
    );

    Map<String, dynamic> toJson() => {
        "case_id": caseId,
        "line": line,
        "until": until,
    };
}


///Response of POST /v1/orders (202 new, 200 same source_id) and PUT /v1/episodes/{id}/order
///(202). Does not mean a preparation exists yet. (APP-02, APP-07)
class OrderAccepted {
    final String episodeId;
    final EpisodeStatus status;

    OrderAccepted({
        required this.episodeId,
        required this.status,
    });

    factory OrderAccepted.fromJson(Map<String, dynamic> json) => OrderAccepted(
        episodeId: json["episode_id"],
        status: episodeStatusValues.map[json["status"]]!,
    );

    Map<String, dynamic> toJson() => {
        "episode_id": episodeId,
        "status": episodeStatusValues.reverse[status],
    };
}


///App -> server: PUT /v1/episodes/{id}/order. The full corrected item list; items without
///item_id are new. The server judges again from S2; only tasks not started yet change.
///(APP-07)
class OrderEdit {
    final List<OrderEditItem> items;

    OrderEdit({
        required this.items,
    });

    factory OrderEdit.fromJson(Map<String, dynamic> json) => OrderEdit(
        items: List<OrderEditItem>.from(json["items"].map((x) => OrderEditItem.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "items": List<dynamic>.from(items.map((x) => x.toJson())),
    };
}

class OrderEditItem {
    final String? itemId;
    final String name;
    final int? qty;

    OrderEditItem({
        this.itemId,
        required this.name,
        required this.qty,
    });

    factory OrderEditItem.fromJson(Map<String, dynamic> json) => OrderEditItem(
        itemId: json["item_id"],
        name: json["name"],
        qty: json["qty"],
    );

    Map<String, dynamic> toJson() => {
        "item_id": itemId,
        "name": name,
        "qty": qty,
    };
}


///App -> server: POST /v1/households/{hid}/pause (request and response). true cancels tasks
///not started yet and stores new orders without judging; running effects continue. (APP-10)
class Pause {
    
    ///Response only.
    final String? householdId;
    final bool paused;

    Pause({
        this.householdId,
        required this.paused,
    });

    factory Pause.fromJson(Map<String, dynamic> json) => Pause(
        householdId: json["household_id"],
        paused: json["paused"],
    );

    Map<String, dynamic> toJson() => {
        "household_id": householdId,
        "paused": paused,
    };
}


///Response of GET /v1/hub/plans: every unfinished plan of the household (latest version
///each) + pause state. (HUB-04)
class PlanPull {
    final int devicesRevision;
    final String householdId;
    
    ///true = start nothing new (APP-10).
    final bool paused;
    final List<Plan> plans;

    PlanPull({
        required this.devicesRevision,
        required this.householdId,
        required this.paused,
        required this.plans,
    });

    factory PlanPull.fromJson(Map<String, dynamic> json) => PlanPull(
        devicesRevision: json["devices_revision"],
        householdId: json["household_id"],
        paused: json["paused"],
        plans: List<Plan>.from(json["plans"].map((x) => Plan.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "devices_revision": devicesRevision,
        "household_id": householdId,
        "paused": paused,
        "plans": List<dynamic>.from(plans.map((x) => x.toJson())),
    };
}


///Preparation plan for one order (C-1 v3). Server -> hub; the hub runs it without
///interpreting values.
///Sent inside GET /v1/hub/plans. A larger plan_version replaces the older one. (HUB-03,
///HUB-04)
class Plan {
    
    ///Every task cancelled so far (cumulative across versions).
    final List<CancelledElement> cancelled;
    
    ///Devices revision the plan was made with. The hub checks at run time that each cmd is
    ///still delegated (else blocked: not_delegated).
    final int devicesRevision;
    final String householdId;
    final String planId;
    final int planVersion;
    final String sentAt;
    
    ///All live tasks of this version.
    final List<TaskElement> tasks;

    Plan({
        required this.cancelled,
        required this.devicesRevision,
        required this.householdId,
        required this.planId,
        required this.planVersion,
        required this.sentAt,
        required this.tasks,
    });

    factory Plan.fromJson(Map<String, dynamic> json) => Plan(
        cancelled: List<CancelledElement>.from(json["cancelled"].map((x) => CancelledElement.fromJson(x))),
        devicesRevision: json["devices_revision"],
        householdId: json["household_id"],
        planId: json["plan_id"],
        planVersion: json["plan_version"],
        sentAt: json["sent_at"],
        tasks: List<TaskElement>.from(json["tasks"].map((x) => TaskElement.fromJson(x))),
    );

    Map<String, dynamic> toJson() => {
        "cancelled": List<dynamic>.from(cancelled.map((x) => x.toJson())),
        "devices_revision": devicesRevision,
        "household_id": householdId,
        "plan_id": planId,
        "plan_version": planVersion,
        "sent_at": sentAt,
        "tasks": List<dynamic>.from(tasks.map((x) => x.toJson())),
    };
}

class CancelledElement {
    
    ///true if the task had started: undo it.
    final bool restore;
    final String taskId;

    CancelledElement({
        required this.restore,
        required this.taskId,
    });

    factory CancelledElement.fromJson(Map<String, dynamic> json) => CancelledElement(
        restore: json["restore"],
        taskId: json["task_id"],
    );

    Map<String, dynamic> toJson() => {
        "restore": restore,
        "task_id": taskId,
    };
}

class TaskElement {
    final List<ActionElement> actions;
    final End end;
    final TaskSource source;
    final String taskId;
    final Trigger trigger;
    final Way way;

    TaskElement({
        required this.actions,
        required this.end,
        required this.source,
        required this.taskId,
        required this.trigger,
        required this.way,
    });

    factory TaskElement.fromJson(Map<String, dynamic> json) => TaskElement(
        actions: List<ActionElement>.from(json["actions"].map((x) => ActionElement.fromJson(x))),
        end: End.fromJson(json["end"]),
        source: taskSourceValues.map[json["source"]]!,
        taskId: json["task_id"],
        trigger: Trigger.fromJson(json["trigger"]),
        way: wayValues.map[json["way"]]!,
    );

    Map<String, dynamic> toJson() => {
        "actions": List<dynamic>.from(actions.map((x) => x.toJson())),
        "end": end.toJson(),
        "source": taskSourceValues.reverse[source],
        "task_id": taskId,
        "trigger": trigger.toJson(),
        "way": wayValues.reverse[way],
    };
}

class ActionElement {
    final String cmd;
    final String device;
    
    ///Absent when the command has no value_schema. An object of numbers / enum strings for
    ///parameter commands; a string only for value_schema 'text' (show_notice).
    final dynamic value;

    ActionElement({
        required this.cmd,
        required this.device,
        this.value,
    });

    factory ActionElement.fromJson(Map<String, dynamic> json) => ActionElement(
        cmd: json["cmd"],
        device: json["device"],
        value: json["value"],
    );

    Map<String, dynamic> toJson() => {
        "cmd": cmd,
        "device": device,
        "value": value,
    };
}


///Exactly one of on / time.
class End {
    
    ///End this long after the end event.
    final String? after;
    
    ///Only an end event caused by this actor counts.
    final By? by;
    
    ///End event.
    final String? on;
    
    ///End this long after the trigger if the end event never comes.
    final String? orAfter;
    
    ///End at this time if the end event never comes.
    final String? orTime;
    
    ///Put devices back to the saved state at the end.
    final bool restore;
    
    ///Absolute end (a household that changed the end point before).
    final String? time;

    End({
        this.after,
        this.by,
        this.on,
        this.orAfter,
        this.orTime,
        required this.restore,
        this.time,
    });

    factory End.fromJson(Map<String, dynamic> json) => End(
        after: json["after"],
        by: byValues.map[json["by"]],
        on: json["on"],
        orAfter: json["or_after"],
        orTime: json["or_time"],
        restore: json["restore"],
        time: json["time"],
    );

    Map<String, dynamic> toJson() => {
        "after": after,
        "by": byValues.reverse[by],
        "on": on,
        "or_after": orAfter,
        "or_time": orTime,
        "restore": restore,
        "time": time,
    };
}

enum TaskSource {
    ITEM,
    SITUATION
}

final taskSourceValues = EnumValues({
    "item": TaskSource.ITEM,
    "situation": TaskSource.SITUATION
});

class Trigger {
    final String? time;
    
    ///With released true: when the package was brought in.
    final String? at;
    final TriggerEvent? event;
    
    ///Run on the first matching event only.
    final bool? firstOnly;
    
    ///package.brought_in only. false = wait; the server sends a new version with true once it
    ///links the delivery to this order (HUB-12).
    final bool? released;
    
    ///Only events inside this window count.
    final Window? window;

    Trigger({
        this.time,
        this.at,
        this.event,
        this.firstOnly,
        this.released,
        this.window,
    });

    factory Trigger.fromJson(Map<String, dynamic> json) => Trigger(
        time: json["time"],
        at: json["at"],
        event: triggerEventValues.map[json["event"]],
        firstOnly: json["first_only"],
        released: json["released"],
        window: json["window"] == null ? null : Window.fromJson(json["window"]),
    );

    Map<String, dynamic> toJson() => {
        "time": time,
        "at": at,
        "event": triggerEventValues.reverse[event],
        "first_only": firstOnly,
        "released": released,
        "window": window?.toJson(),
    };
}


///Only events inside this window count.
class Window {
    final String from;
    final String to;

    Window({
        required this.from,
        required this.to,
    });

    factory Window.fromJson(Map<String, dynamic> json) => Window(
        from: json["from"],
        to: json["to"],
    );

    Map<String, dynamic> toJson() => {
        "from": from,
        "to": to,
    };
}


///Household types. App -> server: PUT /v1/households/{hid}/profile (request and response).
///Blocked combinations (kb/household_types.json) -> 422 household_types_invalid. (APP-12)
class Profile {
    
    ///Response only.
    final String? householdId;
    final List<String> householdTypes;

    Profile({
        this.householdId,
        required this.householdTypes,
    });

    factory Profile.fromJson(Map<String, dynamic> json) => Profile(
        householdId: json["household_id"],
        householdTypes: List<String>.from(json["household_types"].map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "household_id": householdId,
        "household_types": List<dynamic>.from(householdTypes.map((x) => x)),
    };
}


///Why SPIRA prepared what it did, read from stored values (no new LLM call). Server -> app:
///GET /v1/episodes/{id}/rationale. Masked items never appear, only masked_count. (APP-06)
class Rationale {
    final String episodeId;
    final Evidence evidence;
    final List<Execution> executions;
    final List<IntentElement> intents;
    final List<ItemTaskElement> itemTasks;
    final int maskedCount;
    
    ///Set when no intent was found.
    final String? noneReason;
    final List<Observation> observations;
    final List<Task> tasks;
    
    ///Items not part of any intent.
    final List<String> unbundled;

    Rationale({
        required this.episodeId,
        required this.evidence,
        required this.executions,
        required this.intents,
        required this.itemTasks,
        required this.maskedCount,
        required this.noneReason,
        required this.observations,
        required this.tasks,
        required this.unbundled,
    });

    factory Rationale.fromJson(Map<String, dynamic> json) => Rationale(
        episodeId: json["episode_id"],
        evidence: Evidence.fromJson(json["evidence"]),
        executions: List<Execution>.from(json["executions"].map((x) => Execution.fromJson(x))),
        intents: List<IntentElement>.from(json["intents"].map((x) => IntentElement.fromJson(x))),
        itemTasks: List<ItemTaskElement>.from(json["item_tasks"].map((x) => ItemTaskElement.fromJson(x))),
        maskedCount: json["masked_count"],
        noneReason: json["none_reason"],
        observations: List<Observation>.from(json["observations"].map((x) => Observation.fromJson(x))),
        tasks: List<Task>.from(json["tasks"].map((x) => Task.fromJson(x))),
        unbundled: List<String>.from(json["unbundled"].map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "episode_id": episodeId,
        "evidence": evidence.toJson(),
        "executions": List<dynamic>.from(executions.map((x) => x.toJson())),
        "intents": List<dynamic>.from(intents.map((x) => x.toJson())),
        "item_tasks": List<dynamic>.from(itemTasks.map((x) => x.toJson())),
        "masked_count": maskedCount,
        "none_reason": noneReason,
        "observations": List<dynamic>.from(observations.map((x) => x.toJson())),
        "tasks": List<dynamic>.from(tasks.map((x) => x.toJson())),
        "unbundled": List<dynamic>.from(unbundled.map((x) => x)),
    };
}

class Evidence {
    final List<CalendarElement> calendar;
    final List<KbCount>? kbCounts;
    final List<KbExample> kbExamples;
    
    ///e.g. 'few similar cases' when fewer than the minimum.
    final String? kbNote;
    
    ///null when the home context switch was off.
    final UnusualItems? unusualItems;

    Evidence({
        required this.calendar,
        required this.kbCounts,
        required this.kbExamples,
        required this.kbNote,
        required this.unusualItems,
    });

    factory Evidence.fromJson(Map<String, dynamic> json) => Evidence(
        calendar: List<CalendarElement>.from(json["calendar"].map((x) => CalendarElement.fromJson(x))),
        kbCounts: json["kb_counts"] == null ? [] : List<KbCount>.from(json["kb_counts"]!.map((x) => KbCount.fromJson(x))),
        kbExamples: List<KbExample>.from(json["kb_examples"].map((x) => KbExample.fromJson(x))),
        kbNote: json["kb_note"],
        unusualItems: json["unusual_items"] == null ? null : UnusualItems.fromJson(json["unusual_items"]),
    );

    Map<String, dynamic> toJson() => {
        "calendar": List<dynamic>.from(calendar.map((x) => x.toJson())),
        "kb_counts": kbCounts == null ? [] : List<dynamic>.from(kbCounts!.map((x) => x.toJson())),
        "kb_examples": List<dynamic>.from(kbExamples.map((x) => x.toJson())),
        "kb_note": kbNote,
        "unusual_items": unusualItems?.toJson(),
    };
}

class CalendarElement {
    final String day;
    final int daysAfter;
    final String end;
    final String id;
    final String start;
    final List<String> tags;

    CalendarElement({
        required this.day,
        required this.daysAfter,
        required this.end,
        required this.id,
        required this.start,
        required this.tags,
    });

    factory CalendarElement.fromJson(Map<String, dynamic> json) => CalendarElement(
        day: json["day"],
        daysAfter: json["days_after"],
        end: json["end"],
        id: json["id"],
        start: json["start"],
        tags: List<String>.from(json["tags"].map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "day": day,
        "days_after": daysAfter,
        "end": end,
        "id": id,
        "start": start,
        "tags": List<dynamic>.from(tags.map((x) => x)),
    };
}

class KbCount {
    final String intentId;
    final int n;
    final String name;

    KbCount({
        required this.intentId,
        required this.n,
        required this.name,
    });

    factory KbCount.fromJson(Map<String, dynamic> json) => KbCount(
        intentId: json["intent_id"],
        n: json["n"],
        name: json["name"],
    );

    Map<String, dynamic> toJson() => {
        "intent_id": intentId,
        "n": n,
        "name": name,
    };
}

class KbExample {
    final String caseId;
    final String intentId;
    final String? intentText;
    final List<String> items;
    final Overlap overlap;

    KbExample({
        required this.caseId,
        required this.intentId,
        required this.intentText,
        required this.items,
        required this.overlap,
    });

    factory KbExample.fromJson(Map<String, dynamic> json) => KbExample(
        caseId: json["case_id"],
        intentId: json["intent_id"],
        intentText: json["intent_text"],
        items: List<String>.from(json["items"].map((x) => x)),
        overlap: Overlap.fromJson(json["overlap"]),
    );

    Map<String, dynamic> toJson() => {
        "case_id": caseId,
        "intent_id": intentId,
        "intent_text": intentText,
        "items": List<dynamic>.from(items.map((x) => x)),
        "overlap": overlap.toJson(),
    };
}

class Overlap {
    final List<String> items;
    final int k;
    final int n;

    Overlap({
        required this.items,
        required this.k,
        required this.n,
    });

    factory Overlap.fromJson(Map<String, dynamic> json) => Overlap(
        items: List<String>.from(json["items"].map((x) => x)),
        k: json["k"],
        n: json["n"],
    );

    Map<String, dynamic> toJson() => {
        "items": List<dynamic>.from(items.map((x) => x)),
        "k": k,
        "n": n,
    };
}

class UnusualItems {
    final List<UnusualItemsItem>? items;
    final UnusualStatus status;
    final List<String>? usual;

    UnusualItems({
        this.items,
        required this.status,
        this.usual,
    });

    factory UnusualItems.fromJson(Map<String, dynamic> json) => UnusualItems(
        items: json["items"] == null ? [] : List<UnusualItemsItem>.from(json["items"]!.map((x) => UnusualItemsItem.fromJson(x))),
        status: unusualStatusValues.map[json["status"]]!,
        usual: json["usual"] == null ? [] : List<String>.from(json["usual"]!.map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "items": items == null ? [] : List<dynamic>.from(items!.map((x) => x.toJson())),
        "status": unusualStatusValues.reverse[status],
        "usual": usual == null ? [] : List<dynamic>.from(usual!.map((x) => x)),
    };
}

class UnusualItemsItem {
    final String item;
    final String why;

    UnusualItemsItem({
        required this.item,
        required this.why,
    });

    factory UnusualItemsItem.fromJson(Map<String, dynamic> json) => UnusualItemsItem(
        item: json["item"],
        why: json["why"],
    );

    Map<String, dynamic> toJson() => {
        "item": item,
        "why": why,
    };
}

enum UnusualStatus {
    ALL_USUAL,
    INSUFFICIENT,
    LIST
}

final unusualStatusValues = EnumValues({
    "all_usual": UnusualStatus.ALL_USUAL,
    "insufficient": UnusualStatus.INSUFFICIENT,
    "list": UnusualStatus.LIST
});

class Execution {
    final String at;
    final String device;
    final ExecutionStatus status;
    final Substrate substrate;
    final String taskId;

    Execution({
        required this.at,
        required this.device,
        required this.status,
        required this.substrate,
        required this.taskId,
    });

    factory Execution.fromJson(Map<String, dynamic> json) => Execution(
        at: json["at"],
        device: json["device"],
        status: executionStatusValues.map[json["status"]]!,
        substrate: substrateValues.map[json["substrate"]]!,
        taskId: json["task_id"],
    );

    Map<String, dynamic> toJson() => {
        "at": at,
        "device": device,
        "status": executionStatusValues.reverse[status],
        "substrate": substrateValues.reverse[substrate],
        "task_id": taskId,
    };
}

class IntentElement {
    
    ///Evidence per field: item types, calendar event ids, or '가구 유형' (household types).
    final Basis basis;
    final String? calendarEventId;
    final List<String> calendarTags;
    
    ///null when the intent got no card (nothing to prepare).
    final String? cardId;
    final String intentId;
    final String intentText;
    final Situation situation;

    IntentElement({
        required this.basis,
        required this.calendarEventId,
        required this.calendarTags,
        required this.cardId,
        required this.intentId,
        required this.intentText,
        required this.situation,
    });

    factory IntentElement.fromJson(Map<String, dynamic> json) => IntentElement(
        basis: Basis.fromJson(json["basis"]),
        calendarEventId: json["calendar_event_id"],
        calendarTags: List<String>.from(json["calendar_tags"].map((x) => x)),
        cardId: json["card_id"],
        intentId: json["intent_id"],
        intentText: json["intent_text"],
        situation: Situation.fromJson(json["situation"]),
    );

    Map<String, dynamic> toJson() => {
        "basis": basis.toJson(),
        "calendar_event_id": calendarEventId,
        "calendar_tags": List<dynamic>.from(calendarTags.map((x) => x)),
        "card_id": cardId,
        "intent_id": intentId,
        "intent_text": intentText,
        "situation": situation.toJson(),
    };
}


///Evidence per field: item types, calendar event ids, or '가구 유형' (household types).
class Basis {
    final List<String> activity;
    final List<String> event;
    final List<String> guests;
    final List<String> intent;
    final List<String> theme;

    Basis({
        required this.activity,
        required this.event,
        required this.guests,
        required this.intent,
        required this.theme,
    });

    factory Basis.fromJson(Map<String, dynamic> json) => Basis(
        activity: List<String>.from(json["activity"].map((x) => x)),
        event: List<String>.from(json["event"].map((x) => x)),
        guests: List<String>.from(json["guests"].map((x) => x)),
        intent: List<String>.from(json["intent"].map((x) => x)),
        theme: List<String>.from(json["theme"].map((x) => x)),
    );

    Map<String, dynamic> toJson() => {
        "activity": List<dynamic>.from(activity.map((x) => x)),
        "event": List<dynamic>.from(event.map((x) => x)),
        "guests": List<dynamic>.from(guests.map((x) => x)),
        "intent": List<dynamic>.from(intent.map((x) => x)),
        "theme": List<dynamic>.from(theme.map((x) => x)),
    };
}

class Observation {
    final String cardId;
    final List<TaskFeedbackElement> taskFeedback;
    
    ///null until the observation window closes.
    final Verdict? verdict;

    Observation({
        required this.cardId,
        required this.taskFeedback,
        required this.verdict,
    });

    factory Observation.fromJson(Map<String, dynamic> json) => Observation(
        cardId: json["card_id"],
        taskFeedback: List<TaskFeedbackElement>.from(json["task_feedback"].map((x) => TaskFeedbackElement.fromJson(x))),
        verdict: verdictValues.map[json["verdict"]],
    );

    Map<String, dynamic> toJson() => {
        "card_id": cardId,
        "task_feedback": List<dynamic>.from(taskFeedback.map((x) => x.toJson())),
        "verdict": verdictValues.reverse[verdict],
    };
}

class Task {
    final String cardId;
    final List<Device> devices;
    final String line;
    final String need;
    final LineState state;
    final String taskId;
    final Way way;

    Task({
        required this.cardId,
        required this.devices,
        required this.line,
        required this.need,
        required this.state,
        required this.taskId,
        required this.way,
    });

    factory Task.fromJson(Map<String, dynamic> json) => Task(
        cardId: json["card_id"],
        devices: List<Device>.from(json["devices"].map((x) => Device.fromJson(x))),
        line: json["line"],
        need: json["need"],
        state: lineStateValues.map[json["state"]]!,
        taskId: json["task_id"],
        way: wayValues.map[json["way"]]!,
    );

    Map<String, dynamic> toJson() => {
        "card_id": cardId,
        "devices": List<dynamic>.from(devices.map((x) => x.toJson())),
        "line": line,
        "need": need,
        "state": lineStateValues.reverse[state],
        "task_id": taskId,
        "way": wayValues.reverse[way],
    };
}

class Device {
    final String id;
    final String? room;
    final String type;

    Device({
        required this.id,
        required this.room,
        required this.type,
    });

    factory Device.fromJson(Map<String, dynamic> json) => Device(
        id: json["id"],
        room: json["room"],
        type: json["type"],
    );

    Map<String, dynamic> toJson() => {
        "id": id,
        "room": room,
        "type": type,
    };
}


///User reaction on a card. App -> server: POST /v1/cards/{card_id}/reactions. stop = the
///intent is wrong (whole card); line_off / line_on = one line (line_on only before it
///starts). (APP-05)
class Reaction {
    final ReactionEnum reaction;
    final String? taskId;

    Reaction({
        required this.reaction,
        this.taskId,
    });

    factory Reaction.fromJson(Map<String, dynamic> json) => Reaction(
        reaction: reactionEnumValues.map[json["reaction"]]!,
        taskId: json["task_id"],
    );

    Map<String, dynamic> toJson() => {
        "reaction": reactionEnumValues.reverse[reaction],
        "task_id": taskId,
    };
}

enum ReactionEnum {
    LINE_OFF,
    LINE_ON,
    STOP
}

final reactionEnumValues = EnumValues({
    "line_off": ReactionEnum.LINE_OFF,
    "line_on": ReactionEnum.LINE_ON,
    "stop": ReactionEnum.STOP
});

class EnumValues<T> {
    Map<String, T> map;
    late Map<T, String> reverseMap;

    EnumValues(this.map);

    Map<T, String> get reverse {
            reverseMap = map.map((k, v) => MapEntry(v, k));
            return reverseMap;
    }
}
