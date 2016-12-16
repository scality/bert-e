{% extends "message.md" %}

{% block title -%}
Conflict with a changeset in the queue
{% endblock %}

{% block message %}
The changeset in this pull request conflicts with another changeset
already in the queue. Please wait for the current queue to merge into
the development branch. The conflict will then appear in this pull
request and can be sorted on the feature branch directly.

This changeset has *not* been added to the queue. {% endblock %}
