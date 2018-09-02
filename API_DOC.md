__Bert-E__'s API documentation
==============================

Authentication
==============

__Bert-E__'s API can be accessed by users registered with GitHub or Bitbucket.
An OAuth token is required to identify the user and access the API. The token
can be obtained from the Git host provider:

* **Bitbucket**

    Go to https://bitbucket.org/account/user/<your_username>/api
    and create a new consumer with the settings below:

    - permissions:  
        - account: READ access  
        - team membership: READ access  

    Once the consumer created, it is possible to obtain a temporary session token
    to access __Bert-E__'s API (This step is done automatically when the provided
    Python API client is used, and is therefore only required for users wishing
    to access the API via curl or other tools):

```bash
    $ curl --request POST \
           --user "consumer_id:secret" \
           --data grant_type=client_credentials \
           https://bitbucket.org/site/oauth2/access_token
```

* **Github**

    Go to https://github.com/settings/tokens
    and create a new token with the following settings:

    - scopes: user (read:user, user:email and user:follow)

    The obtained token can be used for all subsequent requests on the API, without
    any time limit.

Once a token has been obtained, it is required to authenticate with __Bert-E__.
This step is taken care of automatically when using the Python API client; For
other tools, including curl, see the API endpoint /api/auth for details on how
to create a session.

In all examples below:

* **$URL** contains the full URL to the instance of __Bert-E__
* **$TOKEN** contains a valid token obtained from GitHub. It can be replaced
  with a consumer id and consumer secret when working with a Bitbucket
  repository.


Endpoints
=========


/api/auth
---------

**Methods**

* **GET**

    Authenticate with __Bert-E__ and start a user session.

**Query parameters**

* **access_token**

    A valid access token obtained from the Git host (see introduction above).

**Body data**

Json with user details.

**Responses**

* **200 OK**

    The request has been accepted, and the user details are returned.

* **401 UNAUTHORIZED**

    You are not authenticated.

**Examples**

```bash
$ curl --cookie-jar session \
       --header "Content-type: application/json" \
       "$URL/api/auth?access_token=$TOKEN"

{
  "email": "firstname.lastname@organization.com",
  "name": "Firstname Lastname",
  "picture": "https://avatars1.githubusercontent.com/u/999999999?v=4",
  "preferred_username": "my_github_handle",
  "profile": "https://github.com/my_github_handle",
  "sub": "xxxxxxxx",
  "updated_at": 1531311603,
  "website": ""
}
```

/api/jobs
---------

**Methods**

* **GET**

    List all jobs.

**Query parameters**

<None>

**Body data**

Json with details of all jobs: past (limited to 1000), current and in queue.

**Responses**

* **200 OK**

    The request has been accepted. The returned json contains the details
    of all jobs.

* **401 UNAUTHORIZED**

    You are not authenticated.

/api/jobs/<id>
--------------

**Methods**

* **GET**

    Get the status of the specified job.

**Query parameters**

* **id**

    A job id. This id is returned in the json of all newly created jobs.

**Body data**

Json with details of the specified jobs.

**Responses**

* **200 OK**

    The request has been accepted. The returned json contains the details
    of the job.

* **401 UNAUTHORIZED**

    You are not authenticated.

* **404 NOT FOUND**

    The requested job does not exist or has expired.

/api/pull-requests/<id>
-----------------------

**Methods**

* **POST**

    Create a job that will evaluate the specified pull request and attempt
    at merging it.

**Query parameters**

* **id**

    A positive integer corresponding to the pull request id on the Git host.

**Body data**

<None>

**Responses**

* **202 ACCEPTED**

    The request has been accepted, and a job has been created. The returned
    json contains the details of the job, including it's id.

* **400 BAD REQUEST**

    The syntax of the request is erroneous (typically: incorrect pull
    request id)

* **401 UNAUTHORIZED**

    You are not authenticated.

* **403 FORBIDDEN**

    You are not authorized to access that resource.
    Authenticate with the proper access level first.

**Job results**

* **JobFailure**

    The pull request that was requested does not exist.

* if the pull request is found, the job returns the usual code representing
  the result of the evaluation of the pull request (e.g. Queued, Merged,
  ApprovalRequired, ...). Please check the user documentation for further
  details.


**Examples**

* With curl (after the authentication flow and session cookie has been created):

```bash
$ curl --cookie session \
       --request POST \
       --header "Content-type: application/json" \
       "$URL/api/pull-requests/1337"

<job details>
```

* With the Python API client:

```bash
$ bert-e_api_client --token $TOKEN \
                    --base-url $URL \
                    pull-requests/1337

<job details>
```


/api/gwf/queues
---------------

**Methods**

* **PATCH**

    Create a job that will merge all pull requests currently in
    the queues, irrespective of the status of builds.

    This is useful in case a flaky build is blocking the merge for
    example.

    To be used with extreme caution, since any work landing on
    development branches without proper validation, will impact all
    developpers branching from that point.

* **POST**

    Create a job that will reset all queues and additional pull request jobs
    to reconstruct the queues automatically.

    Use it when:

    * __Bert-E__ reports that queues are out of order,
    * it is required to remove a pull request from the queue, before it is
      merged to the target development branches. In this case, comment the said
      pull request with a **wait** comment to __Bert-E__, then instruct the robot to
      rebuild the queues.

* **DELETE**

    Create a job that will remove all queue data created by __Bert-E__.

    Can be used as a last resort when __Bert-E__ reports a status of
    QueueOutOfOrder for example.

    All branches q/ will be safely removed from the repository. The queues
    will be recreated automatically on the next job. Any pull request that
    was queued at the time of the reset will __NOT__ be queued anymore. It
    will be required to evaluate each pull request manually to add them to
    the queues again (see /api/pull-requests/<id>, or comment the pull
    requests).

**Query parameters**

<None>

**Body data**

<None>

**Responses**

* **202 ACCEPTED**

    The request has been accepted, and a job has been created. The returned
    json contains the details of the job, including it's id.

* **401 UNAUTHORIZED**

    You are not authenticated.

* **403 FORBIDDEN**

    You are not authorized to access that resource.
    Authenticate with the proper access level first.

**Job results**

* **NotMyJob**

    This instance of __Bert-E__ does not support queues.

* **JobSuccess**

    The queues have been deleted (DELETED), or deleted with
    creation of additional pull request jobs (POST).

* In the case of force merge job (PATCH), the usual code of a merge
  is returned (in most cases: Merged). Please check the user documentation.

**Examples**

* With curl (after the authentication flow and session cookie has been created):

```bash
$ curl --cookie session \
       --request POST \
       --header "Content-type: application/json" \
       "$URL/api/queues"

<job details>
```

* With the Python API client:

```bash
$ bert-e_api_client --token $TOKEN \
                    --base-url $URL \
                    --httpmethod DELETE \
                    queues

<job details>
```
