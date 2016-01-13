This pull request has been successfully merged by @{{ wall_e }}.

Releases are:


{% for item in releases -%}
* {{item}}

{% endfor %}

Please switch the associated ticket {{ticket}} to DONE.
