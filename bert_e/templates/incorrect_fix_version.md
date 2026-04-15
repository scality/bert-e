{% extends "message.md" %}

{% block title -%}
Incorrect fix version
{% endblock %}

{% block message %}
The `Fix Version/s` in issue {{ issue.key }} contains:

{% for version in issue_versions %}
* `{{ version }}`
{% else %}
* *None*
{% endfor %}

{% if expect_versions|length == 1 and expect_versions[0].split('.')|length == 4 %}
Considering where you are trying to merge, I expected to find at least:
{% else %}
Considering where you are trying to merge, I ignored possible hotfix versions and I expected to find:
{% endif %}

{% for version in expect_versions %}
* `{{ version }}`
{% else %}
* *None*
{% endfor %}

Please check the `Fix Version/s` of {{ issue.key }}, or the target
branch of this pull request.
{% endblock %}
