# -*- coding: utf-8 -*-
# python modules
import time
import json
import pickle
import sys
from uuid import uuid4
import unicodedata
import shlex, subprocess
import socket
import hashlib
import os
import pkgutil
import requests
from requests.auth import HTTPBasicAuth
import xmltodict
import xmlrpclib
import uuid
import urllib

# flask proper
from flask import render_template, request, session, redirect, make_response, Response, Blueprint, jsonify
from flask.ext.sqlalchemy import SQLAlchemy
from datetime import datetime
from datetime import timedelta

# WSUDOR_Manager
from WSUDOR_Manager import app
from WSUDOR_Manager import models
from WSUDOR_Manager import db
from WSUDOR_Manager import roles
from WSUDOR_Manager.actions import actions
from WSUDOR_Manager import redisHandles
from WSUDOR_Manager import login_manager
from WSUDOR_Manager import WSUDOR_ContentTypes
from WSUDOR_ContentTypes import *
from WSUDOR_API.v1.bitStream import BitStream
import utilities

# flask-security
# from flask_security import Security, SQLAlchemyUserDatastore, UserMixin, RoleMixin

# login
from flask import flash, url_for, abort, g
from flask.ext.login import login_required, login_user, logout_user, current_user

# models
from models import User

# forms
from flask_wtf import Form
from wtforms import TextField

# get celery instance / handle
from WSUDOR_Manager import celery
import jobs
import forms
from redisHandles import *

# localConfig
import localConfig

# Solr
import solrHandles
from solrHandles import solr_handle

# Fedora
from fedoraHandles import fedora_handle

# regex
import re


# GENERAL
#########################################################################################################

@app.route("/")
@login_required
@roles.auth(['admin','metadata','view'])
def index():
    if "username" in session:
        username = session['username']
        return redirect("userPage")
    else:
        username = "User not set."
        return redirect("login")
        # return render_template("index.html", username=username)


@app.route("/about")
@login_required
@roles.auth(['admin'])
def about():

    return render_template("about.html")


@app.route('/userPage')
@login_required
@roles.auth(['admin','metadata','view'])
def userPage():

    # set username in session
    username = session['username']

    # retrieve user data from DB
    user = models.User.query.filter_by(username=username).first()

    # get selected PIDs to show user
    try:
        user.selected_objects_count = len(jobs.getSelPIDs())
    except:
        user.selected_objects_count = 0

    return render_template("userPage.html", user=user)


@app.route('/systemStatus')
@login_required
@roles.auth(['admin','metadata'])
def systemStatus():

    #check important ports
    imp_ports = [
        (localConfig.WSUDOR_MANAGER_PORT, "WSUDOR_Manager"),
        (localConfig.WSUDOR_API_LISTENER_PORT, "WSUDOR_API"),
        (61616, "Fedora Messaging Service"),
        (8080, "Tomcat"),
        (6379, "Redis"),
        (3306, "MySQL")
    ]

    imp_ports_results = []
    for port, desc in imp_ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        check = result = s.connect_ex(("localhost", port))
        if check == 0:
            msg = "active"
        else:
            msg = "inactive"

        imp_ports_results.append((str(port), desc, msg))


    # get celery worker information
    sup_server = xmlrpclib.Server('http://127.0.0.1:9001')
    sup_info = {
        "celery":{},
        "rtail":{}
    }

    # ouroboros
    try:
        ouroboros_info = json.dumps(sup_server.supervisor.getProcessInfo('Ouroboros'))
    except:
        ouroboros_info = False

    # user cw
    try:
        sup_info['celery']['celery-%s' % session['username']] = json.dumps(sup_server.supervisor.getProcessInfo('celery-%s' % session['username']))
    except:
        sup_info['celery']['celery-%s' % session['username']] = False

    # generic cw
    try:
        sup_info['celery']['generic_worker'] = json.dumps(sup_server.supervisor.getProcessInfo('celery-celery'))
    except:
        sup_info['celery']['generic_worker'] = False

    # rtail-server
    try:
        sup_info['rtail']['rtail-server'] = json.dumps(sup_server.supervisor.getProcessInfo('rtail-server'))
    except:
        sup_info['rtail']['rtail-server'] = False

    # user log streaming
    try:
        sup_info['rtail']['rtail-celery-%s' % session['username']] = json.dumps(sup_server.supervisor.getProcessInfo('rtail-celery-%s' % session['username']))
    except:
        sup_info['rtail']['rtail-celery-%s' % session['username']] = False

    # ouroboros error streaming
    try:
        sup_info['rtail']['rtail-ouroboros-err'] = json.dumps(sup_server.supervisor.getProcessInfo('rtail-ouroboros-err'))
    except:
        sup_info['rtail']['rtail-ouroboros-err'] = False

    # celery-celery streaming
    try:
        sup_info['rtail']['rtail-celery-celery'] = json.dumps(sup_server.supervisor.getProcessInfo('rtail-celery-celery'))
    except:
        sup_info['rtail']['rtail-celery-celery'] = False

    # render template
    return render_template("systemStatus.html", imp_ports_results=imp_ports_results, ouroboros_info=ouroboros_info, sup_info=sup_info)


@app.route('/systemStatus/cw/<target>/<action>')
@login_required
@roles.auth(['admin','metadata'])
def cw(target, action):


    if target == "celery-%s" % session['username']:
        # grab user
        user = models.User.query.filter_by(username=session['username']).first()
        # grab model
        cw = models.CeleryWorker(user.username)

    elif target == 'rtail-celery-%s' % session['username']:

        # define the supervisor process
        supervisor_process = '''[program:rtail-celery-%(username)s]
command=/bin/bash -c "tail -F /var/log/celery-%(username)s.err.log | /usr/local/bin/rtail --id celery-%(username)s"
user = ouroboros
autostart=true
autorestart=true
stopasgroup=true

killasgroup=true''' % {'username': session['username']}
        cw = models.createSupervisorProcess('rtail-celery-%s' % session['username'], supervisor_process, "rtail")

    elif target == 'rtail-server':
        supervisor_process = '''[program:rtail-server]
command=/usr/local/bin/rtail-server
user = ouroboros
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true'''

        cw = models.createSupervisorProcess('rtail-server', supervisor_process, "rtail", True)

    elif target == 'rtail-ouroboros-err':
        supervisor_process = '''[program:rtail-ouroboros-err]
command=/bin/bash -c "tail -F /var/log/ouroboros.err.log | /usr/local/bin/rtail --id ouroboros-error"
user = ouroboros
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true'''
        cw = models.createSupervisorProcess('rtail-ouroboros-err', supervisor_process, "rtail")

    elif target == 'rtail-celery-celery':
        supervisor_process = '''[program:rtail-celery-celery]
command=/bin/bash -c "tail -F /var/log/celery-celery.err.log | /usr/local/bin/rtail --id celery-celery"
user = ouroboros
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true'''
        cw = models.createSupervisorProcess('rtail-celery-celery', supervisor_process, "rtail")

    else:
        # grab model
        cw = models.CeleryWorker("celery")

    # start
    if action == 'start':
        cw.start()

    # restart
    if action == 'restart':
        cw.restart()

    # stop
    if action == 'stop':
        cw.stop()

    return redirect("systemStatus")


@app.route('/email', methods=['GET','POST'])
def email():
# Uses external smtp mail server to send email; looking for parameters for 'subject', 'msg', 'from', and 'to'

    # if (localConfig.EMAIL_PASSPHRASE === request.args.get('passphrase')):
    #     data = {'from':request.args.get('from'), 'to':request.args.get('to'), 'subject':request.args.get('subject'), 'msg':request.args.get('msg')}
    #     email = utilities.Email()

    #     if email.send(data):
    #         resp = make_response("", 200)
    #     else:
    #         resp = abort(500)
    
    # return resp
    # data = {'from': request.form.get('from'), 'to': request.form.get('to'), 'subject': request.form.get('subject'), 'msg': request.form.get('msg')}
    # return request.form.get
    # print request.get_data(False, True, True)
    print request.data
    print request.headers
    print request.form
    resp = make_response(request.form.get('from', "stuff"), 200)
    # email = utilities.Email()

    # if email.send(data):
    #     resp = make_response("stuffasdf", 200)
    # else:
    #     abort(500)
    return resp


    # return redirect("problemObjs")

# MAJOR SUB-SECTIONS
#########################################################################################################
@app.route('/contentModels', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin'])
def contentModels():

    # WSUDOR_ContentTypes
    wcts = [name for _, name, _ in pkgutil.iter_modules(['WSUDOR_ContentTypes'])]
    print wcts

    return render_template("contentModels.html", wcts=wcts)


@app.route('/MODSedit', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin','metadata','view'])
def MODSedit():
    return render_template("MODSedit.html")


@app.route('/datastreamManagement', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin','metadata','view'])
def datastreamManagement():
    return render_template("datastreamManagement.html")


@app.route('/objectManagement', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin','metadata','view'])
def objectManagement():
    return render_template("objectManagement.html")


@app.route('/WSUDORManagement', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin','metadata','view'])
def WSUDORManagement():
    return render_template("WSUDORManagement.html")

# LOGIN
#########################################################################################################
# Use @login_required when you want to lock down a page


@app.before_request
def before_request():

    # This is executed before every request
    g.user = current_user
    session['reportedObjs'] = int(models.user_pids.query.filter_by(username="problemBot").count())

@login_manager.user_loader
def load_user(id):
    """
    Flask-Login user_loader callback.
    The user_loader function asks this function to get a User Object or return
    None based on the userid.
    The userid was stored in the session environment by Flask-Login.
    user_loader stores the returned User object in current_user during every
    flask request.
    """

    user = User.query.get(int(id))
    if user is not None:
        user.id = session['user_id']
        return user
    else:
        return None

##########################
# WSUDOR BASED LOGIN
##########################
@app.route("/login", methods=["GET", "POST"])
def login():

    # check for WSUDOR cookie
    if "WSUDOR" in request.cookies:

        # parse cookie
        session_id = urllib.unquote(request.cookies['WSUDOR'])

        # ping wsudorauth
        '''
        best way to do this?
            - HTTP request
            - other?
        '''
        r = requests.get('%s/wsudorauth/session_check/%s' % (localConfig.WSUDORAUTH_BASE_URL, session_id) )
        wsudorauth_check_status_code = r.status_code
        wsudorauth_check_data = json.loads(r.content)

        # code 200, user found in active sessions
        if wsudorauth_check_status_code == 200:

            username = wsudorauth_check_data['username']

            # check if user exists
            exists = db.session.query(db.exists().where(User.username == username)).scalar()

            # user found in database, compare with cookie credentials
            if exists:

                # get user
                user = User.get(username)

                # check if user enriched from ldap
                if user.username == user.displayName:
                    print "user has not logged in, update now?"

                # login
                user = User.get(username)
                login_user(user, remember=True)

                # Login to Fedora with eulfedora and set session variables
                utilities.login(username)
                session['username'] = username

                # Rtail
                try:
                    sup_server = xmlrpclib.Server('http://127.0.0.1:9001')
                    sup_info = {}
                    sup_info['rtail-server'] = sup_server.supervisor.getProcessInfo('rtail-server')
                    if sup_info['rtail-server']['statename'] == "RUNNING":

                        # Make sure to start the user's own log streaming
                        supervisor_name = 'rtail-celery-%s' % session['username']
                        supervisor_process = '''[program:rtail-celery-%(username)s]
    command=/bin/bash -c "tail -F /var/log/celery-%(username)s.err.log | /usr/local/bin/rtail --id celery-%(username)s"
    user = ouroboros
    autostart=true
    autorestart=true
    stopasgroup=true
    killasgroup=true''' % {'username':session['username']}
                        # create Log streamer for user
                        print "streaming activity log for %s celery worker " % session['username']
                        stream_cw = models.createSupervisorProcess(supervisor_name,supervisor_process, "rtail")
                        stream_cw.start()
                except:
                    print "Rtail-server not running; therefore, not creating a log streamer for current user"

                # Go to page
                return redirect(request.args.get('next') or url_for('index'))

            else:
                return jsonify({
                        'msg':'Sorry, an Ouroboros account has not yet been created for "%s".  Please contact an administrator to have an account created.' % (username),
                        'login_url':localConfig.LOGIN_URL
                    })

        # code 404, no active session found
        elif wsudorauth_check_status_code == 400:
            return jsonify({
                    'msg':'Sorry, a session id was not found in your WSUDOR cookie.',
                    'login_url':localConfig.LOGIN_URL
                })

        # code 404, no active session found
        elif wsudorauth_check_status_code == 404:
            return jsonify({
                    'msg':'Sorry, an active session was not found for %s.' % (session_id),
                    'login_url':localConfig.LOGIN_URL
                })

    # if WSUDOR cookie not found, redirect to login
    else:
        return redirect(localConfig.LOGIN_URL)


@app.route('/logout')
def logout():

    print "logging out..."

    # stop user-based celery log streaming
    stream_cw = models.createSupervisorProcess('rtail-celery-%s' % session['username'], False, "rtail")
    stream_cw.stop()
    session["username"] = ""
    logout_user()

    # delete WSUDOR cookie and redirect
    print "removing WSUDOR cookie from client"
    response = make_response(redirect(url_for('index')))
    response.set_cookie('WSUDOR', '', expires=0)
    return response

##########################
# WSUDOR USERS
##########################

# create user
@app.route('/users/create', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin'])
def createUser():

    if request.method == 'POST':
        print "creating user: %s" % (request.form['username'])
        roles = request.form.getlist('role')
        user = User(
            request.form['username'],
            roles,
            request.form['username'],
        )
        db.session.add(user)
        db.session.commit()
        flash('User successfully registered')
        return redirect(url_for('users_view'))

    elif request.method == 'GET': 
        return render_template('createUser.html')


# view all users
@app.route('/users/view', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin'])
def users_view():

    users = models.User.query.all()
    return render_template('usersView.html', APP_PREFIX=localConfig.APP_PREFIX, users=users)


# view all users
@app.route('/user/<username>/edit', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin'])
def editUser(username):

    if request.method == 'POST':
        print "editing user: %s" % (username)
        
        # get user
        user = models.User.get(username)
        
        # get form data
        roles = request.form.getlist('role')
        
        # update model      
        user.role = ','.join(roles)
        user.displayName = request.form['displayName']
        db.session.commit()
        flash('User successfully edited')
        return redirect(url_for('users_view'))

    else:
        user = models.User.get(username)
        return render_template('editUser.html', APP_PREFIX=localConfig.APP_PREFIX, user=user)


# view all users
@app.route('/user/<username>/delete', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin'])
def deleteUser(username):

    # delete user
    models.User.query.filter_by(username=username).delete()
    db.session.commit()
    return redirect(url_for('users_view'))


# current user WSUDOR credentials
@app.route('/user/current/WSUDOR_credentials', methods=['GET', 'POST'])
@login_required
@roles.auth(['admin'])
def credentials():

    # parse cookie
    unquoted_cookie_string = urllib.unquote(request.cookies['WSUDOR'])
    return jsonify(json.loads(unquoted_cookie_string))


# current user WSUDOR credentials
@app.route('/users/authfail', methods=['GET', 'POST'])
@login_required
def authfail():

    route_roles = request.args['route_roles'].split(",")

    return jsonify({
        'msg':'your roles do not permit you to view this page',
        'route_roles':route_roles,
        'user_roles':g.user.roles()
        })




# JOB MANAGEMENT
#########################################################################################################

# confirmation page for objects, serializes relevant request objects as "job_package"
@app.route("/fireTask/<job_type>/<task_name>", methods=['POST', 'GET'])
def fireTask(job_type,task_name):

    username = session['username']

    # create job_package
    job_package = {
        "username":username,
        "form_data":request.values,
        "job_type":job_type
    }

    # pass along binary uploaded data if included in job task
    # writes to temp file in /tmp/Ouroboros
    temp_filename = "/tmp/Ouroboros/"+str(uuid.uuid4())
    if 'upload' in request.files and request.files['upload'].filename != '':
        print "Form provided file, uploading and reading file to variable"
        # print request.files['upload']
        # write uploaded file to temp file
        with open(temp_filename,'w') as fhand:
            fhand.write(request.files['upload'].read())
        job_package['upload_data'] = temp_filename

    if 'upload_path' in request.form and request.form['upload_path'] != '':
        print "Form provided path, reading file to variable"
        # print request.form['upload_path']
        # create symlink from path to temp file
        os.symlink(request.form['upload_path'], temp_filename)
        job_package['upload_data'] = temp_filename


    task_inputs_key = username+"_"+task_name+"_"+str(int(time.time()))
    print "Assigning to Redis-Cached key:",task_inputs_key
    redisHandles.r_job_handle.set(task_inputs_key,pickle.dumps(job_package))

    if job_type == "obj_loop":
        print "Firing job for obj_loop type"
        # get PIDs to confirm
        PIDs = jobs.getSelPIDs()
        return render_template("objConfirm.html",task_name=task_name,task_inputs_key=task_inputs_key,PIDs=PIDs,username=username,localConfig=localConfig)

    if job_type == "custom_loop":
        print "Firing job for custom_loop type"
        return redirect("fireTaskWorker/%s/%s" % (task_name,task_inputs_key))


# confirmation page for objects, serializes relevant request objects as "job_package"
@app.route("/cancelTask/<task_inputs_key>", methods=['POST', 'GET'])
@roles.auth(['admin'])
def cancelTask(task_inputs_key):

    print redisHandles.r_job_handle.delete(task_inputs_key)
    return redirect("userPage")


# fireTaskWorker is the factory that begins tasks from WSUDOR_Manager.actions
@app.route("/fireTaskWorker/<task_name>/<task_inputs_key>", methods=['POST', 'GET'])
def fireTaskWorker(task_name,task_inputs_key):

    print "Starting task request..."

    # get job_package and burn it
    job_package = pickle.loads(redisHandles.r_job_handle.get(task_inputs_key))
    redisHandles.r_job_handle.delete(task_inputs_key)

    # check if task in available tasks, else abort
    try:
        '''
        In the case of custom_loop's, using this task_handle to fire instead of taskFactory
        '''
        task_handle = getattr(actions, task_name)
        print "We've got task handle:",task_handle
    except:
        return utilities.applicationError("Task not found, or user not authorized to perform.  Return to <a href='/{{APP_PREFIX}}/userPage'>user page</a>.")

    # get username from session (will pull from user auth session later)
    username = session['username']
    job_package['username'] = username

    # instantiate job number and add to job_package
    ''' pulling from incrementing redis counter, considering MySQL '''
    job_num = jobs.jobStart()
    job_package['job_num'] = job_num

    print "Job Type is:",job_package['job_type']


    # Object Loop
    #####################################################################################################################
    if job_package['job_type'] == "obj_loop":

        # get user-selectedd objects
        stime = time.time()
        userSelectedPIDs = models.user_pids.query.filter_by(username=username,status=True)
        PIDlist = [PID.PID for PID in userSelectedPIDs]
        etime = time.time()
        ttime = (etime - stime) * 1000
        print "Took this long to create list from SQL query",ttime,"ms"

        # begin job and set estimated tasks
        print "Antipcating",userSelectedPIDs.count(),"tasks...."
        redisHandles.r_job_handle.set("job_{job_num}_est_count".format(job_num=job_num),userSelectedPIDs.count())

        # send to celeryTaskFactory in actions.py
        '''
        iterates through PIDs and creates secondary async tasks for each
        passing username, task_name, and job_package containing all the update handles
        'celery_task_id' below contains celery task key, that contains all eventual children objects
        '''
        celery_task_id = actions.obj_loop_taskFactory.apply_async(
            kwargs={
                'job_num':job_num,
                'task_name':task_name,
                'job_package':job_package,
                'PIDlist':PIDlist
            },
            queue=username
        )


    # Custom Loop
    #####################################################################################################################
    if job_package['job_type'] == "custom_loop":

        '''
        Fire particular task. This task handle is pulled from actions above,
        and it should act like a taskFactory of sorts for the custom loop.
        '''
        celery_task_id = task_handle.apply_async(
            kwargs={
                'job_package':job_package
            },
            queue=username
        )



    # Generic Cleanup
    #####################################################################################################################

    # send job to user_jobs SQL table
    db.session.add(models.user_jobs(job_num, username, celery_task_id, "init", task_name))
    db.session.commit()

    print "Started job #",job_num,"Celery task #",celery_task_id
    try:
        return redirect("userJobs")
    except:
        return "API call or not logged in."


#status of currently running, spooling, or pending jobs for user
@app.route("/userJobs")
@roles.auth(['admin','metadata'])
def userJobs():

    username = session['username']

    # get user jobs
    user_jobs_list = models.user_jobs.query.filter(models.user_jobs.status != "complete", models.user_jobs.status != "retired", models.user_jobs.username == username)

    # return package
    return_package = []

    for job in user_jobs_list:

        # get job num
        job_num = job.job_num

        # create package
        status_package = {}
        status_package["job_num"] = job_num #this is pulled from SQL table

        # get estimated tasks
        job_est_count = redisHandles.r_job_handle.get("job_%s_est_count" % (job_num))

        # get assigned tasks
        job_assign_count = redisHandles.r_job_handle.get("job_%s_assign_count" % (job_num))
        if job_assign_count == None:
            job_assign_count = 0

        # get completed tasks
        job_complete_count = redisHandles.r_job_handle.get("job_%s_complete_count" % (job_num))
        if job_complete_count == None:
            job_complete_count = 0

        # DEBUG
        # print job
        # print job_est_count, job_assign_count, job_complete_count

        # compute percentage complete
        if all([job_complete_count,job_est_count]) != None and all([job_complete_count,job_est_count]) > 0:
            comp_percent = '{0:.0%}'.format(float(job_complete_count) / float(job_est_count))
        else:
            comp_percent = 'N/A'

        # spooling, works on stable jobHand object
        if job_assign_count > 0 and job_assign_count < job_est_count :
            status_package['job_status'] = "spooling"
            job.status = "spooling"

        # check if pending
        elif job_assign_count == job_est_count and job_complete_count == 0:
            # special case for single item jobs
            if int(job_est_count) == 1:
                status_package['job_status'] = "running"
                job.status = "running"
            else:
                status_package['job_status'] = "pending"
                job.status = "pending"      

        # check if completed
        elif job_complete_count == job_est_count:
            status_package['job_status'] = "complete"
            # udpate job status in SQL db here
            job.status = "complete"
            # update redis end time (etime)
            r_job_handle.set("job_%s_etime" % (job_num),int(time.time()))
            print "Job Complete!  Updated in SQL."

        # else, must be running
        else:
            status_package['job_status'] = "running"

        # determine time elapsed / remaining
        def formatTime(seconds):
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            return "%d:%02d:%02d" % (h, m, s)

        def returnTimeRemaining(total_seconds=False):
            if total_seconds == False:
                rtime = int( (float(elapsed_seconds) / float(job_complete_count)) * float(job_est_count) ) - float(elapsed_seconds)
                if rtime < 0:
                    return 0
                else:
                    return rtime


        # elapsed
        try:
            elapsed_seconds = int( time.time() - int(redisHandles.r_job_handle.get("job_%s_stime" % (job_num))) )
            time_elapsed = formatTime(elapsed_seconds)
        except:
            time_elapsed = "Unknown"

        # remaining
        if job_est_count != None and int(job_est_count) == 1:
            time_remaining = "Unknown"
        elif job_complete_count == 0:
            time_remaining = "Estimating"
        elif 'job_%s_complete_count' % (job_num) not in session or 'job_%s_time_remaining' % (job_num) not in session or int(job_complete_count) > int(session['job_%s_complete_count' % (job_num)]):
            session['job_%s_complete_count' % (job_num)] = int(job_complete_count)
            seconds_remaining = returnTimeRemaining()
            session['job_%s_time_remaining' % (job_num)] = seconds_remaining
            time_remaining = formatTime(seconds_remaining)
            # print "updating comp count and time remaining : %s %s" % (job_complete_count, seconds_remaining)
        else:
            time_remaining = formatTime( int(session['job_%s_time_remaining' % (job_num)]) )


        # data return
        response_dict = {
            "job_num":job_num,
            "job_name":job.job_name,
            "job_status":status_package['job_status'],
            "assigned_tasks":job_assign_count,
            "completed_tasks":job_complete_count,
            "estimated_tasks":job_est_count,
            "comp_percent":comp_percent,
            "time_elapsed":time_elapsed,
            "time_remaining":time_remaining
        }

        # return_package[status_package["job_num"]] = response_dict
        return_package.append(response_dict)

    # commit all changes to SQL db
    db.session.commit()

    # return return_package
    if request.args.get("data","") == "true":
        json_string = json.dumps(return_package)
        resp = make_response(json_string)
        resp.headers['Content-Type'] = 'application/json'
        return resp
    else:
        return render_template("userJobs.html",username=username,localConfig=localConfig)


# see all user jobs, including completed
@app.route("/userAllJobs")
@login_required
@roles.auth(['admin','metadata'])
def userAllJobs():

    username = session['username']

    # get user jobs
    user_jobs_list = models.user_jobs.query.filter(models.user_jobs.username == username)

    # return package
    return_package = []

    for job in user_jobs_list:

        job_package = {}
        job_package['job_num'] = job.job_num
        job_package['status'] = job.status
        job_package['job_name'] = job.job_name

        # push to return package
        return_package.append(job_package)

    return render_template("userAllJobs.html",username=session['username'],return_package=return_package)


# Details of a given job
@app.route("/jobDetails/<job_num>")
@roles.auth(['admin','metadata'])
def jobDetails(job_num):

    # get number of estimate tasks
    job_est_count = redisHandles.r_job_handle.get("job_%s_est_count" % (job_num))
    if job_est_count:
        job_task_num = int(job_est_count)
    elif job_est_count == None:
        job_task_num = 0

    # get parent object
    job_SQL = db.session.query(models.user_jobs).filter(models.user_jobs.job_num == job_num).first()
    print "job celery task id:",job_SQL.celery_task_id

    job_details = jobs.getTaskDetails(job_SQL.celery_task_id)
    print job_details

    # get tasks
    tasks_package = {}
    tasks_package['SUCCESS'] = []
    tasks_package['PENDING'] = []
    tasks_package['RETRY'] = []
    tasks_package['FAILURE'] = []

    if job_details.children != None:
        for child in job_details.children:
            tasks_package[child.status].append([child.task_id,child.task_name])
        return render_template("jobDetails.html", job_num=job_num, tasks_package=tasks_package)
    else:
        return render_template("jobDetails.html", job_num=job_num)


# Details of a given task
@app.route("/taskDetails/<task_id>/<job_num>")
@roles.auth(['admin','metadata'])
def taskDetails(task_id,job_num):

    if task_id != "NULL":
        # async, celery status
        task_async = jobs.getTaskDetails(task_id)

        try:
            task_returns = redisHandles.r_job_handle.get(task_id).split(",")
            PID = task_returns[1]
        except:
            PID = "N/A"

    else:
        print "We're dealing with a local job, not Celerized"
        PID = "N/A"
        task_async = {
            "status":"N/A",
            "result":"N/A"
        }

    return render_template("taskDetails.html",task_async=task_async,PID=PID)


# Remove job from SQL, remove tasks from Redis
@app.route("/jobRemove/<job_num>", methods=['POST', 'GET'])
@roles.auth(['admin','metadata'])
def jobRemove(job_num):

    if request.method == "POST" and request.form['commit'] == "true":
        print "Removing job %s" % (job_num)
        result = jobs.jobRemove_worker(job_num)
        print result

        return render_template("jobRemove.html",job_num=job_num,result=result)

    return render_template("jobRemove.html",job_num=job_num)


# Remove job from SQL, remove tasks from Redis
@app.route("/jobRetire/<job_num>", methods=['POST', 'GET'])
@roles.auth(['admin','metadata'])
def jobRetire(job_num):

    result = jobs.jobRetire_worker(job_num)
    print result

    return redirect("userJobs")


# Remove job from SQL, remove tasks from Redis
@app.route("/flushPIDLock", methods=['POST', 'GET'])
@roles.auth(['admin','metadata'])
def flushPIDLock():
    result = redisHandles.r_PIDlock.flushdb()
    print "Result of PID Lock flush:",result
    return render_template("flushPIDLock.html",result=result)


# see all user jobs, including completed
@app.route("/retireAllJobs")
@roles.auth(['admin','metadata'])
def retireAllJobs():

    username = session['username']

    # get user jobs
    user_jobs_list = models.user_jobs.query.filter(models.user_jobs.username == username)

    # return package
    return_package = []

    for job in user_jobs_list:
        if job.status != "complete":
            result = jobs.jobRetire_worker(job.job_num)

    print "All non-complete jobs, retired"

    return redirect("userJobs")


# Flush all User Jobs (clear Celery tasks from Redis DB)
@app.route("/flushCeleryTasks")
@roles.auth(['admin','metadata'])
def flushCeleryTasks():

    # get username from session
    username = session['username']

    # clear broker
    broker_size = redisHandles.r_broker.dbsize()
    broker_clear = redisHandles.r_broker.flushdb()

    if broker_clear == True:
        msg = "%s tasks cleared from Celery broker." % (str(broker_size))
    else:
        msg = "Errors were had."

    return render_template("flushCeleryTasks.html",msg=msg)


# Push subset of job to workspace PID group
@app.route("/pushJobPIDs/<job_num>/<result>", methods=['POST', 'GET'])
@login_required
@roles.auth(['admin','metadata'])
def pushJobPIDs(job_num,result):

    print "creating workspace group of PIDs that were result: %s" % result

    # get username from session
    username = session['username']

    # get parent object
    job_SQL = db.session.query(models.user_jobs).filter(models.user_jobs.job_num == job_num).first()
    print "job celery task id:",job_SQL.celery_task_id

    # get celery parent
    job_details = jobs.getTaskDetails(job_SQL.celery_task_id)
    print job_details

    # get tasks
    PIDs = []

    # iterate through children, and retrieve PID from results
    if job_details.children != None:

        # iterate through celery tasks
        for child in job_details.children:
            # async, celery status
            task_result, PID = redisHandles.r_job_handle.get(child.task_id).split(",")
            if task_result == result:
                PIDs.append(PID)

    print PIDs

    print "adding to MySQL"

    # get PIDs group_name
    group_name = str('%s_%s_%s' % (username,job_num,result))

    # add PIDs to SQL
    jobs.sendUserPIDs(username,PIDs,group_name)

    # commit
    db.session.commit()

    # redirect
    return redirect("userWorkspace")



# OBJECT MANAGEMENT
####################################################################################

# View to get 30,000 ft handle one Objects slated to be acted on
@app.route("/objPreview/<PIDnum>", methods=['POST', 'GET'])
@login_required
@utilities.objects_needed
@roles.auth(['admin','metadata','view'])
def objPreview(PIDnum):

    object_package = {}

    # GET CURRENT OBJECTS
    PIDlet = jobs.genPIDlet(int(PIDnum))
    if PIDlet == False:
        return utilities.applicationError("PIDnum is out of range or invalid.  Object-at-a-Glance is displeased.")
    PIDlet['pURL'] = "/objPreview/"+str(int(PIDnum)-1)
    PIDlet['nURL'] = "/objPreview/"+str(int(PIDnum)+1)

    # WSUDOR handle
    obj_handle = WSUDOR_ContentTypes.WSUDOR_Object(PIDlet['cPID'])

    # General Metadata
    solr_params = {'q':utilities.escapeSolrArg(PIDlet['cPID']), 'rows':1}
    solr_results = solr_handle.search(**solr_params)
    if solr_results.total_results == 0:
        return "Selected objects don't appear to exist."
    solr_package = solr_results.documents[0]
    object_package['solr_package'] = solr_package

    # COMPONENTS
    object_package['components_package'] = []
    riquery = fedora_handle.risearch.spo_search(subject=None, predicate="info:fedora/fedora-system:def/relations-external#isMemberOf", object="info:fedora/"+PIDlet['cPID'])
    for s,p,o in riquery:
        object_package['components_package'].append(s.encode('utf-8'))
    if len(object_package['components_package']) == 0:
        object_package.pop('components_package')

    # RDF RELATIONSHIPS
    riquery = fedora_handle.risearch.spo_search(subject="info:fedora/"+PIDlet['cPID'], predicate=None, object=None)

    # parse
    riquery_filtered = []
    for s,p,o in riquery:
        riquery_filtered.append((p,o))
    riquery_filtered.sort()
    object_package['rdf_package'] = riquery_filtered

    # DATASTREAMS
    ds_list = obj_handle.ohandle.ds_list
    object_package['datastream_package'] = ds_list

    # Object size of datastreams
    size_dict = obj_handle.update_objSizeDict()
    object_package['size_dict'] = size_dict
    object_package['size_dict_json'] = json.dumps(size_dict)

    # OAI
    OAI_dict = {}
    #identifer
    try:
        riquery = fedora_handle.risearch.spo_search(subject="info:fedora/"+PIDlet['cPID'], predicate="http://www.openarchives.org/OAI/2.0/itemID", object=None)
        OAI_ID = riquery.objects().next().encode('utf-8')
        OAI_dict['ID'] = OAI_ID
    except:
        print "No OAI Identifier found."

    # sets
    OAI_dict['sets'] = []
    try:
        riquery = fedora_handle.risearch.spo_search(subject="info:fedora/"+PIDlet['cPID'], predicate="http://digital.library.wayne.edu/fedora/objects/wayne:WSUDOR-Fedora-Relations/datastreams/RELATIONS/content/isMemberOfOAISet", object=None)
        for each in riquery.objects():
            OAI_dict['sets'].append(each)
    except:
        print "No OAI sets found."

    object_package['OAI_package'] = OAI_dict
    print object_package['OAI_package']

    # RENDER
    return render_template("objPreview.html", PIDnum=(int(PIDnum)+1), PIDlet=PIDlet, object_package=object_package, localConfig=localConfig)


# PID check for user
@app.route("/userWorkspace")
@login_required
@roles.auth(['admin','metadata','view'])
def userWorkspace():
    # get username from session
    username = session['username']

    # gen group list
    user_pid_groups = db.session.query(models.user_pids).filter(models.user_pids.username == username).group_by("group_name")
    group_names = [each.group_name.encode('ascii','ignore') for each in user_pid_groups]

    # pass the current PIDs to page as list
    return render_template("userWorkspace.html",username=username, group_names=group_names, localConfig=localConfig)


# PID check for user
@app.route("/selObjsOverview")
@login_required
@roles.auth(['admin','metadata','view'])
def selObjsOverview():

    # get username from session
    username = session['username']
    PIDs = jobs.getSelPIDs()


    # Solr stats
    stats = {}
    query = 'id:'+' OR id:'.join(PIDs)
    query = query.replace("wayne:","wayne\:")
    results = solr_handle.search(**{ "q":query, "fq":["obj_size_i:*"], "fl":"id obj_size_i", "stats":"true", "stats.field":"obj_size_i", "rows":0 })
    stats['solr'] = results.stats

    # human stats
    stats['human'] = {
        'sum':utilities.sizeof_fmt(results.stats['obj_size_i']['sum'])
    }

    # pass the current PIDs to page as list
    return render_template("selObjsOverview.html", stats=stats)


# Select / Deselect / Remove PIDs from user list
@app.route("/PIDmanageAction/<action>", methods=['POST', 'GET'])
@roles.auth(['admin','metadata','view'])
def PIDmanageAction(action):
    # get username from session
    username = session['username']
    print "Current action is:",action

    # if post AND group toggle
    if request.method == 'POST' and action == 'group_toggle':
        group_name = request.form['group_name']
        db.session.execute("UPDATE user_pids SET status = CASE WHEN status = False THEN True ELSE False END WHERE username = '%s' AND group_name = '%s';" % (username, group_name))

    # select all
    if action == "s_all":
        print "All PIDs selected..."
        db.session.query(models.user_pids).filter(models.user_pids.username == username).update({'status': True})

    # select none
    if action == "s_none":
        print "All PIDs unselected..."
        db.session.query(models.user_pids).filter(models.user_pids.username == username).update({'status': False})

    # select toggle
    if action == "s_toggle":
        print "All PIDs toggling..."
        db.session.execute("UPDATE user_pids SET status = CASE WHEN status = False THEN True ELSE False END WHERE username = '%s';" % (username))

    # delete selections
    if action == "s_del":
        db.session.query(models.user_pids).filter(models.user_pids.username == username, models.user_pids.status == True).delete()

    # commit changes
    db.session.commit()

    return "Update Complete."

    # pass the current PIDs to page as list
    return redirect("PIDmanage")


# small function toggle selection of PIDs
@app.route("/PIDRowUpdate/<id>/<action>/<status>")
@roles.auth(['admin','metadata','view'])
def PIDRowUpdate(id,action,status):
    # get username from session
    username = session['username']

    # update single row status
    if action == "update_status":
        # get PID with query
        PID = models.user_pids.query.filter(models.user_pids.id == id)[0]
        # update
        if status == "toggle":
            # where PID.status equals current status in SQL
            if PID.status == False:
                PID.status = True
            elif PID.status == True:
                PID.status = False
        else:
            PID.status = status

    # delete single row
    if action == "delete":
        # get PID with query
        PID = models.user_pids.query.filter(models.user_pids.id == id)[0]
        db.session.delete(PID)
        print "Deleted PID id#",id,"from SQL database"

    # commit
    db.session.commit()

    return "PID updated."


# PID selection via Solr
@app.route("/PIDSolr", methods=['POST', 'GET'])
@roles.auth(['admin','metadata','view'])
@login_required
def PIDSolr():

    # get username from session
    username = session['username']

    # get form
    form = forms.solrSearch(request.form)

    # collection selection
    coll_query = {'q':"rels_hasContentModel:*Collection", 'fl':["id","dc_title"], 'rows':1000}
    coll_results = solr_handle.search(**coll_query)
    coll_docs = coll_results.documents

    # check for title, give generic if not present
    for each in coll_docs:
        if 'dc_title' not in each:
            each['dc_title'] = [ 'Unknown Collection Title' + each['id'].encode('ascii','ignore') ]

    form.collection_object.choices = [(each['id'].encode('ascii','ignore'), each['dc_title'][0].encode('ascii','ignore')) for each in coll_docs]
    form.collection_object.choices.insert(0,("","All Collections"))

    # content model
    cm_query = {'q':'*', 'facet' : 'true', 'facet.field' : 'rels_hasContentModel'}
    cm_results = solr_handle.search(**cm_query)
    form.content_model.choices = [(each, each.split(":")[-1]) for each in cm_results.facets['facet_fields']['rels_hasContentModel']]
    form.content_model.choices.insert(0,("","All Content Types"))

    # perform search
    if request.method == 'POST':

        # build base with native Solr queries
        query = {'q':form.q.data, 'fq':[form.fq.data], 'fl':[form.fl.data], 'rows':100000}

        # Fedora RELS-EXT
        # collection selection
        if form.collection_object.data:
            print "Collection refinement:",form.collection_object.data
            escaped_coll = form.collection_object.data.replace(":","\:")
            query['fq'].append("rels_isMemberOfCollection:info\:fedora/"+escaped_coll)


        # content model / type selection
        if form.content_model.data:
            print "Content Model refinement:",form.content_model.data
            escaped_cm = form.content_model.data.replace(":","\:")
            query['fq'].append("rels_hasContentModel:"+escaped_cm)



        # issue query
        print query
        stime = time.time()
        q_results = solr_handle.search(**query)
        etime = time.time()
        ttime = (etime - stime) * 1000
        print "Solr Query took:",ttime,"ms"
        output_dict = {}
        data = []
        stime = time.time()
        for each in q_results.documents:
            try:
                PID = each['id'].encode('ascii','ignore')
                dc_title = each['dc_title'][0].encode('ascii','ignore')
                data.append([PID,dc_title])
            except:
                print "Could not render:",each['id'] #unicdoe solr id
        etime = time.time()
        ttime = (etime - stime) * 1000
        print "Solr Munging for DataTables took::",ttime,"ms"

        output_dict['data'] = data
        json_output = json.dumps(data)

        return render_template("PIDSolr.html",username=username, form=form, q_results=q_results, json_output=json_output, coll_docs=coll_docs,APP_HOST=localConfig.APP_HOST)

    # pass the current PIDs to page as list
    return render_template("PIDSolr.html",username=username, form=form, coll_docs=coll_docs,APP_HOST=localConfig.APP_HOST)


# PID check for user
@app.route("/updatePIDsfromSolr/<update_type>", methods=['POST', 'GET'])
@roles.auth(['admin','metadata','view'])
def updatePIDsfromSolr(update_type):

    # get username from session
    username = session['username']
    print "Sending PIDs to",username

    # retrieve PIDs
    PIDs = request.form['json_package']
    PIDs = json.loads(PIDs)

    # get PIDs group_name
    group_name = request.form['group_name'].encode('ascii','ignore')

    # add PIDs to SQL
    if update_type == "add":
        jobs.sendUserPIDs(username,PIDs,group_name)

    # remove PIDs from SQL
    if update_type == "remove":
        print "removing each PID from SQL..."
        jobs.removeUserPIDs(username,PIDs)
        print "...complete."

    return "Update Complete."


# PID check for user
@app.route("/quickPID", methods=['POST', 'GET'])
@login_required
@roles.auth(['admin','metadata','view'])
def quickPID():

    # get username from session
    username = session['username']

    PID = request.args.get('pid')
    print "quick adding",PID

    # add PID to MySQL
    PIDs = [PID]

    # deselect all PIDs
    db.session.query(models.user_pids).filter(models.user_pids.username == username).update({'status': False})

    # get PIDs group_name
    group_name = 'boutique'

    # add PIDs to SQL
    jobs.sendUserPIDs(username,PIDs,group_name)

    # get PID with query
    PID_handle = models.user_pids.query.filter_by(PID=PID,group_name='boutique').first()

    # select
    PID_handle.status = True

    # commit
    db.session.commit()

    # redirect
    return redirect("objPreview/0")

# Retrieve all user-reported problem Objects
@app.route("/problemObjs", methods=['POST', 'GET'])
@login_required
@roles.auth(['admin','metadata','view'])
def problemObjs():

    problemObjs = models.user_pids.query.filter_by(username="problemBot").all()
    saDict = {}
    saList = []
    for each in problemObjs:
        saDict = each.__dict__
        # General Metadata
        solr_params = {'q':utilities.escapeSolrArg(str(saDict['PID'])), 'rows':1}
        solr_results = solr_handle.search(**solr_params)
        if solr_results.total_results == 0:
            return "Selected objects don't appear to exist."
        solr_package = solr_results.documents[0]
        saDict['solr_package'] = solr_package

        # rehydrate the unicode string that holds the form data into a dictionary
        if isinstance(saDict['notes'], unicode):
            saDict['notes'] = json.loads(saDict['notes'])
        saList.append(saDict.copy())

    return render_template("problemObjs.html",problemObjs=saList,APP_HOST=localConfig.APP_HOST)


# Retrieve all user-reported problem Objects
@app.route("/claimObj", methods=['POST', 'GET'])
@login_required
@roles.auth(['admin','metadata'])
def claimObj():

    orig_obj = request.form['pid']
    obj, num = orig_obj.split('-')
    num = int(num)

    problemObjs = models.user_pids.query.filter_by(PID=obj).filter_by(username="problemBot").filter_by(id=num).all()
    for certain_obj in problemObjs:
        certain_obj.username = session['username']
        db.session.commit()

    return "True"


# Retrieve all user-reported problem Objects
@app.route("/removeObj", methods=['POST', 'GET'])
@login_required
@roles.auth(['admin','metadata'])
def removeObj():

    orig_obj = request.form['pid']
    obj, num = orig_obj.split('-')
    num = int(num)

    problemObjs = models.user_pids.query.filter_by(PID=obj).filter_by(username="problemBot").filter_by(id=num).all()
    for certain_obj in problemObjs:
        db.session.delete(certain_obj)
        db.session.commit()

    return "True"

# Create index of all routes to send as JSON to whoever requests
@app.route("/routeIndexer", methods=['POST', 'GET'])
def routeIndexer():
    initial = [rule.rule for rule in app.url_map.iter_rules() if rule.endpoint !='static']

    pattern = re.compile(r'^\/*<[^<]*$')
    secondary = []
    for each in initial:
        match = re.search(pattern, each)
        if not match:
            secondary.append(each)

    pattern = re.compile(r'^\/[^\/]*$')
    endpoints = []
    pagesDict = {}
    for each in secondary:
        match = re.search(pattern, each)
        if match:
            if each[1:] is "":
                pagesDict["label"] = "Home"
            else:
                pagesDict["label"] = each[1:]
            pagesDict["url"] = APP_HOST + "/" + APP_PREFIX + each
            endpoints.append(pagesDict.copy())

    return json.dumps(list(endpoints))

# WSUDOR MANAGEMENT
####################################################################################

# Clear imageServer Cache
@app.route("/imgServerCacheClear")
@roles.auth(['admin'])
def imgServerCacheClear():

    # run os command an return results
    results = os.system("rm /tmp/imageServer/*")
    if results == 0:
        msg = "imageServer Cache successfully cleared."
    else:
        msg = "An error was had: %s" % (results)

    return render_template("simpleMessage.html",msg=msg, heading="imageServer Cache Management")


# Clear imageServer Cache
@app.route("/clearSymLinks")
@roles.auth(['admin'])
def clearSymLinks():

    # run os command an return results
    results = os.system("rm /var/www/wsuls/symLinks/*")
    if results == 0:
        msg = "symLInks successfully cleared."
    else:
        msg = "An error was had: %s" % (results)

    return render_template("simpleMessage.html",msg=msg, heading="symLinks Management")



# Clear user exported BagIt object archives
@app.route("/clearExportBagItArchives")
@roles.auth(['admin'])
def clearExportBagItArchives():

    # get username from session
    username = session['username']
    target_dir = "/var/www/wsuls/Ouroboros/export/%s" % (username)

    # run os command and return results
    results = os.system("rm -r %s/*" % (target_dir))

    if results == 0:
        msg = "User exported, BagIt archives successfully cleared."
    else:
        msg = "An error was had: %s" % (results)

    return render_template("exportBagClear.html",msg=msg)



# Collections Overview
@app.route("/collectionsOverview")
@login_required
@roles.auth(['admin','metadata','view'])
def collectionsOverview():

    # get username from session
    username = session['username']
    # get objects
    PIDs = jobs.getSelPIDs()

    object_package = {}

    # get collection objects
    '''
    This can be improved
    '''
    riquery = fedora_handle.risearch.get_subjects(predicate="info:fedora/fedora-system:def/relations-external#hasContentModel", object="info:fedora/CM:Collection")
    collections = list(riquery)

    # assemble sizes for collections
    object_package['coll_size_dict'] = {}
    for collection in collections:
        print "Working on",collection
        results = solr_handle.search(**{ "q":"rels_isMemberOfCollection:"+collection.replace(":","\:"), "stats":"true", "stats.field":"obj_size_i", "rows":0 })
        print results.stats

        if results != None and results.total_results > 0 and results.stats['obj_size_i'] != None:
            collection_obj_sum = results.stats['obj_size_i']['sum']
            object_package['coll_size_dict'][collection] = (collection_obj_sum,utilities.sizeof_fmt(collection_obj_sum),results.total_results)

    # print object_package['coll_size_dict']
    object_package['coll_size_dict'] = json.dumps(object_package['coll_size_dict'])


    # assemble sizes for content models (cm)
    cms = [name.split("_")[-1] for _, name, _ in pkgutil.iter_modules(['WSUDOR_ContentTypes'])]

    object_package['cm_size_dict'] = {}
    for cm in cms:
        print "Working on",cm
        cm = "info:fedora/CM:%s" % cm
        results = solr_handle.search(**{ "q":"rels_hasContentModel:"+cm.replace(":","\:"), "stats":"true", "stats.field":"obj_size_i", "rows":0 })
        print results.stats

        if results != None and results.total_results > 0 and results.stats['obj_size_i'] != None:
            collection_obj_sum = results.stats['obj_size_i']['sum']
            object_package['cm_size_dict'][cm] = (collection_obj_sum,utilities.sizeof_fmt(collection_obj_sum),results.total_results)

    # print object_package['cm_size_dict']
    object_package['cm_size_dict'] = json.dumps(object_package['cm_size_dict'])

    return render_template("collectionsOverview.html", object_package=object_package)



# Run Generic Method from WSUDOR Object
@app.route("/genericMethod", methods=['POST', 'GET'])
@login_required
@roles.auth(['admin'])
def genericMethod():

    # iterate through content types
    methods = set() 
    for ct in dir(WSUDOR_ContentTypes):
        if not ct.startswith("__"):
            methods.update(dir(getattr(WSUDOR_ContentTypes,ct)))
    methods_list = list(methods)
    methods_list.sort()
    return render_template("genericMethod.html", methods_list=methods_list)





# WSUDOR_ContentTypes (aka "wct")
####################################################################################

# wct investigator
@app.route("/wcts/<wct>", methods=['POST', 'GET'])
@roles.auth(['admin'])
def wcts(wct):

    print "Opening",wct
    wct = globals()[wct]

    return render_template("wctUtilities.html",wct=wct)




# preview solr document values (a la eulindexer / indexdata functions from eulfedora)
@app.route("/solrDoc/<pid>", methods=['POST', 'GET'])
@roles.auth(['admin','metadata'])
def solrDoc(pid):

    o = WSUDOR_ContentTypes.WSUDOR_Object(pid)
    json_string = json.dumps(o.previewSolrDict())
    resp = make_response(json_string)
    resp.headers['Content-Type'] = 'application/json'
    return resp


# returns document as run through readux
@app.route("/solrReaduxDoc/<pid>/<action>", methods=['POST', 'GET'])
# @roles.auth(['admin','metadata','view'])
def solrReaduxDoc(pid, action):

    '''
    This is not currently working with roles, and does appear to hang sometimes.
    '''

    try:
        r = requests.get('%s/indexdata/%s' % (localConfig.READUX_BASE_URL, pid)).json()
    except:
        print "could not retrieve index data from readux, aborting"
        return jsonify({"result":False})

    # fix times
    if 'created' in r:
        r['created'] = datetime.strptime(r['created'],'%Y-%m-%dT%H:%M:%S.%f+00:00').strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    if 'last_modified' in r:
        r['last_modified'] = datetime.strptime(r['last_modified'],'%Y-%m-%dT%H:%M:%S.%f+00:00').strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    # view
    if action == 'view':
        json_string = json.dumps(r)
        resp = make_response(json_string)
        resp.headers['Content-Type'] = 'application/json'
        return resp

    # index into readux solr
    if action == 'index':
        response = solrHandles.onDemand('readux').update([r],'json',commit=True)
        json_string = json.dumps(response.raw_content)
        resp = make_response(json_string)
        resp.headers['Content-Type'] = 'application/json'
        return resp



# Advanced Access / Object Admin
####################################################################################

# wct investigator
@app.route("/admin_object_overview/<pid>", methods=['POST', 'GET'])
@roles.auth(['admin','metadata','view'])
def objAccess(pid):

    object_package = {}

    # WSUDOR handle
    obj_handle = WSUDOR_ContentTypes.WSUDOR_Object(pid)

    # General Metadata
    solr_params = {'q':utilities.escapeSolrArg(pid), 'rows':1}
    solr_results = solr_handle.search(**solr_params)
    if solr_results.total_results == 0:
        return "Selected objects don't appear to exist."
    solr_package = solr_results.documents[0]
    object_package['solr_package'] = solr_package

    # COMPONENTS
    object_package['components_package'] = []
    riquery = fedora_handle.risearch.spo_search(subject=None, predicate="info:fedora/fedora-system:def/relations-external#isMemberOf", object="info:fedora/"+pid)
    for s,p,o in riquery:
        object_package['components_package'].append(s.encode('utf-8'))
    if len(object_package['components_package']) == 0:
        object_package.pop('components_package')

    # RDF RELATIONSHIPS
    riquery = fedora_handle.risearch.spo_search(subject="info:fedora/"+pid, predicate=None, object=None)

    # parse
    riquery_filtered = []
    for s,p,o in riquery:
        riquery_filtered.append((p,o))
    riquery_filtered.sort()
    object_package['rdf_package'] = riquery_filtered

    # DATASTREAMS
    ds_list = obj_handle.ohandle.ds_list
    object_package['datastream_package'] = ds_list

    # Object size of datastreams
    if 'update' in request.args:
        size_dict = obj_handle.update_objSizeDict()
    else:   
        size_dict = obj_handle.objSizeDict
    object_package['size_dict'] = size_dict
    object_package['size_dict_json'] = json.dumps(size_dict)

    # OAI
    OAI_dict = {}
    #identifer
    try:
        riquery = fedora_handle.risearch.spo_search(subject="info:fedora/"+pid, predicate="http://www.openarchives.org/OAI/2.0/itemID", object=None)
        OAI_ID = riquery.objects().next().encode('utf-8')
        OAI_dict['ID'] = OAI_ID
    except:
        print "No OAI Identifier found."

    # sets
    OAI_dict['sets'] = []
    try:
        riquery = fedora_handle.risearch.spo_search(subject="info:fedora/"+pid, predicate="http://digital.library.wayne.edu/fedora/objects/wayne:WSUDOR-Fedora-Relations/datastreams/RELATIONS/content/isMemberOfOAISet", object=None)
        for each in riquery.objects():
            OAI_dict['sets'].append(each)
    except:
        print "No OAI sets found."

    object_package['OAI_package'] = OAI_dict
    print object_package['OAI_package']

    # bitStream tokens
    object_package['bitStream_tokens'] = BitStream.genAllTokens(pid, localConfig.BITSTREAM_KEY)

    # RENDER
    return render_template("admin_object_access.html", pid=pid, object_package=object_package, localConfig=localConfig)




######################################################
# Catch all - DON'T REMOVE
######################################################
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
@roles.auth(['admin','metadata','view'])
def catch_all(path):
    return render_template("404.html")
