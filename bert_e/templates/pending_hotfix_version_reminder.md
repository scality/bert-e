{% extends "message.md" %}

{% block title -%}
Pending hotfix branch
{% endblock %}

{% block message %}
:information_source: Issue {{ issue.key }} contains the following
pre-GA hotfix fix version(s):

{% for version in hotfix_versions %}
* `{{ version }}`
{% endfor %}

This means the change is expected to land on the corresponding hotfix
branch as well. Please make sure to open a separate cherry-pick pull
request targeting that hotfix branch so that the fix is applied
everywhere it needs to be.
{% endblock %}
