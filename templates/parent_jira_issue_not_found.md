{% extends "message.md" %}

{% block title -%}
Jira parent issue not found
{% endblock %}

{% block message %}
Parent Jira issue {{ parent }} of subtask {{ issue }} not found.
{% endblock %}
