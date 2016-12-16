{% extends "message.md" %}

{% block title -%}
Partial merge
{% endblock %}

{% block message %}
Apparently, new commits were added to the source branch after I had queued this
Pull Request. As a result, I have merged only **part of** it into the targetted
development branches:

{% for branch in branches %}
* :heavy_check_mark: `{{ branch.name }}`
{% endfor %}

I will now work on the following commits:

{% for commit in commits %}
* #{{commit}}
{% endfor %}

**Please avoid this situation next time.**

As a friendly reminder, you can use the `wait` command to prevent me from processing your
pull-request while your work is still in progress.
{% endblock %}
