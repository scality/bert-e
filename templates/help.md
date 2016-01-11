# User manual #

Wall-E is a robot designed to help developers at Scality merge their code
in the different development branches (`development/4.3`, ...) of the Ring.

## Requirements for a successful merge ##

Wall-E can only merge the code if a set of rules is applied to pull-requests,
branches and associated tickets. Wall-E helps the participants in a
pull-request correct the items that do not follow the rules, by issuing a
status report.

There are different stages in the merge of a pull-request:

* Verification that the minimum information required for the process is
  correct
* creation of temporary integration branches in the repository
* verification that the author and the reviewers of the pull-request
  agree for the merge, and verification of the build status
* merge on all destination branches

1. The rules to progress to the **creation of the integration branches** are:
    * the destination branch must be a `development/*.*`
    * the source branch must have a prefix that is valid for the destination
      branch
    * the branch name must contain a valid Jira ticket
    * the diff introduced by the branch is less than 1000 lines

2. The rules to progress to the **final merge** are, in addition to the rules
   above:
    * check that all conflicts have been resolved
    * check that reviewers have approved the pull-request
    * check that the author has approved the pull-request
    * check that the build status is green
    * check that the Fix Version field in the Jira ticket is coherent

## Pull-request options ##

The behaviour of Wall-E can be customised to fit the needs of each specific
pull-requests.

In order to activate an option for this pull-request, address a comment to
@scality_wall-e including the names of the required options. The option remains
valid as long as the comment remains present in the pull-request. To remove the
option, delete the related comment.

Some options require special privileges. Only a predefined list of users can
activate these options (namely, the members of Releng team). If you need such
an option is required on a pull-request, please include a member of Releng as
a reviewer.

See below for the list of available options and their effect on the
pull-request.

> **Example**
>
> By default, Wall-E only needs one reviewer to consider the code is valid.
> But the author of the pull-request wishes to get the approval of all
> reviewers before merging the code.
>
> To activate the option **unanimity**, the author of the pull-request
> (or any other participant),
> can address the following comment to @scality_wall-e:
>
> ```
> @scality_wall-e unanimity
> ```
>
> If later, the developer changes his mind, and believes only one reviewer is
> enough,
> he/she should delete the comment.

## Wall-E commands ##

It is possible to instruct Wall-E to operate some one-time operations on your
pull-requests. These are called Wall-E's commands. The mechanism behind
commands is similar to options, with the only difference being that once the
command has been executed, Wall-E will ignore the comment that contains it.

> **Example**
>
> A participant wishes to check the status of his pull-request with Wall-E.
>
> Issuing the command **status** will instruct Wall-E to publish a report:
>
> ```
> @scality_wall-e status
> ```

## Options ##

name   | description  | privileged
------ | ------------ | ------------
{% for option in options -%}
**{{option}}** | {{options[option].help}} | {{options[option].priviledged}}
{% endfor %}

## Commands ##

name   | description  | privileged
------ | ------------ | ------------
{% for cmd in commands -%}
**{{cmd}}** | {{commands[cmd].help}} | {{commands[cmd].priviledged}}
{% endfor %}
