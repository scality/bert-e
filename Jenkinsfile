#!groovy
import groovy.json.JsonOutput


def notifyBitbucket(state, key, commit, url) {
    def bitbucketURL = "https://api.bitbucket.org/2.0" +
                       "/repositories/scality/wall-e" +
                       "/commit/${commit}/statuses/build"

    def payload = JsonOutput.toJson([state: state,
                                     key: key,
                                     name: "build and validation pipeline",
                                     url: url])

    withCredentials([[$class: 'UsernamePasswordBinding',
                      credentialsId: 'jenkins',
                      variable: 'CREDS']])
    {
        sh 'curl --silent --user $CREDS ' +
           "--header 'Content-Type: application/json '" +
           "--request POST --data '${payload}' ${bitbucketURL}"
    }
}


def build_status = 'SUCCESSFUL'
def git_commit = ''
def short_commit = ''


stage name: 'initialisation'
    node('master') {
        checkout scm
        sh('git rev-parse HEAD > GIT_COMMIT')
        git_commit=readFile('GIT_COMMIT')
        short_commit=git_commit.take(6)
        stash name: 'repository'

        notifyBitbucket('INPROGRESS',
                        'pipeline',
                        short_commit,
                        "${env.BUILD_URL}console")
    }


stage concurrency: 1, name: 'build'
    node('small') {
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

                sh '''python test_wall_e.py \\
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
        notifyBitbucket(build_status,
                        'pipeline',
                        short_commit,
                        "${env.BUILD_URL}console")

        if (build_status == 'FAILED') {
            currentBuild.result = 'FAILURE'
        }
    }
