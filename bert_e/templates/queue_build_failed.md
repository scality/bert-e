{% extends "message.md" %}

{% block title -%}
Queue build failed
{% endblock %}

{% block message %}

The corresponding build for the queue failed:

- Checkout the [status page]({{ frontend_url }}).
- Identify the failing build and review the logs.
- If no issue is found, re-run the build.

{% endblock %}
