{% extends "message.md" %}

{% block title -%}
Integration data created
{% endblock %}

{% block message %}
I have created the integration data for the additional destination branches.

* this pull request will merge `{{ wbranches[0].src_branch }}` into
`{{ wbranches[0].dst_branch }}`
{% for branch in wbranches[1:] -%}
* {% if githost == 'bitbucket' -%}
    [{{ branch.name }}](https://bitbucket.org/{{ owner }}/{{ slug }}/branch/{{ branch.name }}?dest={{ branch.dst_branch }})
  {%- elif githost == 'github' -%}
    [{{ branch.name }}](https://github.com/{{ owner }}/{{ slug }}/compare/{{ branch.dst_branch }}...{{ branch.name }})
  {%- else -%}
    `{{ branch.name }}`
  {%- endif %} will be merged into `{{ branch.dst_branch }}` {% if child_prs %}(pull request #{{ child_prs[loop.index].id }}){% endif %}
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
{% elif wbranches[1:] %}
You can set option `create_pull_requests` if you need me to create
**integration pull requests** in addition to integration branches, with:

```
@{{ bert_e }} create_pull_requests
```
{% endif %}


{% endblock %}
