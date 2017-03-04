{% extends "message.md" %}

{% block title -%}
Reset warning
{% endblock %}

{% block message %}
There seems to be *manual* commits on integration branches (e.g. conflict
resolutions) that will be lost if you chose to *reset*.

**You can use the `force_reset` command if you still want me
to delete those branches.**

{% endblock %}
