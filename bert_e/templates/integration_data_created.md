{% extends "message.md" %}

{% block title -%}
Integration data created
{% endblock %}

{% block message %}
I have created the integration data for the newer destination branches.

This pull request will merge `{{ wbranches[0].src_branch }}` into
`{{ wbranches[0].dst_branch }}`.


{% for branch in wbranches[1:] -%}
* `{{ branch.name }}` will be merged into `{{ branch.dst_branch }}`
  {% if child_prs %}(pull request #{{ child_prs[loop.index].id }}){% endif %}
{% endfor %}

{% if ignored %}
The following branches will **NOT** be impacted:

{% for branch_name in ignored -%}
* `{{ branch_name }}`
{% endfor %}
{% endif %}

{% if child_prs %}
*Follow* integration pull requests if you would like to be notified of
build statuses by email.
{% else %}
{% if wbranches[1:] %}
You can set option `create_pull_requests` if you need me to create
**integration pull requests** in addition to integration branches, e.g.
publish this comment:

```
@{{ bert_e }} create_pull_requests
```
{% endif %}

{% endif %}

{% endblock %}
