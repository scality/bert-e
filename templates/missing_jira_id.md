{% extends "message.md" %}

{% block title -%}
Missing Jira issue
{% endblock %}

{% block message %}
You must specify a Jira issue in the source branch name in order to
be able to merge to {% branch %}.

It is only possible to merge code without a ticket reference in the
most recent development branch.
{% endblock %}
