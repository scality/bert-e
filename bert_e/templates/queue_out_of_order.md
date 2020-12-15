{% extends "message.md" %}

{% block title -%}
Queue out of order
{% endblock %}

{% block message %}
The changeset has received all authorizations to enter the merge queue,
however the merge queue is currently in an incoherent state. In order
to protect this pull-request, I have not added the changeset to the
queue.

Please contact a member of release engineering.

{% endblock %}
