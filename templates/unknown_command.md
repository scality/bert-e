{% extends "message.md" %}

{% block title -%}
Unknown command
{% endblock %}

{% block message %}
I didn't understand this comment by {{ author }}:

> {{ comment }}

I don't know what `{{ command }}` means.

Please **edit** or **delete** the corresponding comment so I can move on. As
a reminder, you can type `@scality_wall-e help` to get the list of valid
commands.
{% endblock %}
