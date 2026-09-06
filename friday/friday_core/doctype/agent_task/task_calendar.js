// Copyright (c) 2026, Friday Labs and contributors
// For license information, please see license.txt
//
// Calendar + Gantt registration for Task (design 65b).
//
// Gantt is NOT automatic in Frappe: the list-view switcher only offers the
// Gantt (and Calendar) button when `frappe.views.calendar[doctype]` is
// registered, and the Gantt view reads `field_map` to learn which fields are
// the start/end of each bar. Two Date fields on the DocType are necessary but
// not sufficient — this file is what names them and turns the view on.
//
// `gantt: true` activates BOTH the Calendar and Gantt views from one
// registration (the same pattern core uses for ToDo and Event).

frappe.views.calendar["Agent Task"] = {
	field_map: {
		start: "exp_start_date",
		end: "exp_end_date",
		id: "name",
		title: "title",
		progress: "progress",
		// Color the bar by the task's color field (defaulted from the agent).
		color: "color",
	},
	gantt: true,
	get_events_method: "frappe.desk.calendar.get_events",
};
