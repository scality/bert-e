#!groovy
import groovy.json.JsonSlurper
import groovy.json.JsonOutput


def repo_slug = "wall-e"
def build_status = 'SUCCESSFUL'
def git_commit = ''
def git_branch = ''
def short_commit = ''
has_pr_list = false


def notifyBitbucket(repository, branch, commit, name,
                    key, build_url, state, post_message) {
    withCredentials([[$class: 'UsernamePasswordBinding',
                      credentialsId: 'jenkins',
                      variable: 'CREDS']])
    {
        // update build status
        def build_status_url = "https://api.bitbucket.org/2.0" +
                               "/repositories/scality/${repository}" +
                               "/commit/${commit}/statuses/build"

        def payload = JsonOutput.toJson([state: state,
                                         key: key,
                                         name: name,
                                         url: build_url])

        sh 'curl --silent --user $CREDS ' +
           "--header 'Content-Type: application/json '" +
           "--request POST --data '${payload}' ${build_status_url}"

        if (post_message) {
            if (!has_pr_list) {
                // get list of related pull requests
                def branch_ = java.net.URLEncoder.encode(branch)

                def pr_list_url = "https://bitbucket.org/api/2.0" +
                                  "/repositories/scality/${repository}" +
                                  "/pullrequests?q=state%3D%22OPEN%22%20" +
                                  "AND%20source.branch.name%3D" +
                                  "%22${branch_}%22"

                sh 'curl --silent --user $CREDS ' +
                   "--header 'Content-Type: application/json '" +
                   "--request GET ${pr_list_url} > prs_json"

                has_pr_list = true
            }

            prs_json = readFile('prs_json')
            def prs = new JsonSlurper().parseText(prs_json)

            def emoji = ""
            if (state == "FAILED") {
                emoji = ":heavy_exclamation_mark:"
            } else {
                emoji = ":heavy_check_mark:"
            }
            def payload_comment = JsonOutput.toJson(
                    [content: "${emoji} **${name}** is `${state}` " +
                              "on commit `${commit}` and branch `${branch}`"])

            prs.values.each {
                // comment on all related pull requests
                def pr_comment_url = "https://bitbucket.org/api/1.0" +
                                     "/repositories/scality/${repository}" +
                                     "/pullrequests/${it.id}/comments"

                sh 'curl --silent --user $CREDS ' +
                   "--header 'Content-Type: application/json ' --request POST " +
                   "--data '${payload_comment}' ${pr_comment_url}"
            }
        }
    }
}


stage name: 'initialisation'
    node('master') {
        checkout scm
        sh('git rev-parse HEAD > GIT_COMMIT')
        git_commit=readFile('GIT_COMMIT')
        short_commit=git_commit.take(6)
        git_branch=env.BRANCH_NAME

        stash name: 'repository'

        notifyBitbucket(repo_slug, git_branch, short_commit,
                        "build",
                        "pipeline", "${env.BUILD_URL}console",
                        "INPROGRESS", false)
    }


stage concurrency: 1, name: 'build'
    node('trusty-small') {
        unstash 'repository'

        try {
            withCredentials([[$class: 'UsernamePasswordMultiBinding',
                              credentialsId: 'wall-e',
                              passwordVariable: 'WALL_E_PASSWORD',
                              usernameVariable: 'WALL_E_USERNAME'
                             ],
                             [$class: 'UsernamePasswordMultiBinding',
                              credentialsId: 'tester-of-wall-e',
                              passwordVariable: 'TESTER_PASSWORD',
                              usernameVariable: 'TESTER_USERNAME'
                             ],
                             [$class: 'UsernamePasswordMultiBinding',
                              credentialsId: 'eva',
                              passwordVariable: 'EVA_PASSWORD',
                              usernameVariable: 'EVA_USERNAME'
                             ]]) {

                sh '''flake8 *.py'''

                sh '''python test_wall_e.py \\
                          -v \\
                          --repo-prefix _test_wall_e_jenkins \\
                          ${WALL_E_PASSWORD} \\
                          ${EVA_PASSWORD} \\
                          ${TESTER_USERNAME} \\
                          ${TESTER_PASSWORD} \\
                          sylvain.killian@scality.com'''
            }
        } catch (e) {
            build_status = 'FAILED'
        }
    }


stage name: 'finalisation'
    node('master') {
        notifyBitbucket(repo_slug, git_branch, short_commit,
                        "build",
                        "pipeline", "${env.BUILD_URL}console",
                        build_status, true)

        if (build_status == 'FAILED') {
            currentBuild.result = 'FAILURE'
        }
    }
