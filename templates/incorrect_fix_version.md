{% extends "message.md" %}

{% block title -%}
Incorrect fix version
{% endblock %}

{% block message %}
The `Fix Version/s` in issue {{ issue }} contains:

{% for issue in issues %}
* `{{ issue }}`
{% endfor %}

Considering where you are trying to merge, I expected to find:

{% for expect in expects %}
* `{{ expect }}`
{% endfor %}

Please check the `Fix Version/s` or the target branch of this pull request.
{% endblock %}
