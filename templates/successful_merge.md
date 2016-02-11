{% extends "message.md" %}

{% block message %}
I have successfully merged the changeset of this pull request
into targetted development branches:

{% for branch in branches %}
* {{ branch.name }}
{% endfor %}

Please check the status of the associated issue {{ issue }}.

Goodbye {{author}}.
{% endblock %}
