# utilities
import datetime
import hashlib
import requests
from requests.auth import HTTPBasicAuth
from flask import render_template, session
import json
import pickle
from functools import wraps
import mimetypes
import xmlrpclib
from lxml import etree
import re


from localConfig import *
from WSUDOR_Manager import models, app, fedoraHandles, celery
from eulfedora.server import Repository


from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

def login(username):

    print "Logging in..."

    # fire user celery worker
    print "firing user celery worker for: %s" % username
    cw = models.CeleryWorker(username)
    cw.start()      


escapeRules = {'+': r'\+',
             '-': r'\-',
             '&': r'%26',
             '|': r'\|',
             '!': r'\!',
             '(': r'\(',
             ')': r'\)',
             '{': r'\{',
             '}': r'\}',
             '[': r'\[',
             ']': r'\]',
             '^': r'\^',
             '~': r'\~',             
             '?': r'\?',
             ':': r'\:',             
             ';': r'\;',             
             ' ': r'+'
             }

def escapedSeq(term):
        """ Yield the next string based on the
                next character (either this char
                or escaped version """
        for char in term:
                if char in escapeRules.keys():
                        yield escapeRules[char]
                else:
                        yield char

def escapeSolrArg(term):
        """ Apply escaping to the passed in query terms
                escaping special characters like : , etc"""
        term = term.replace('\\', r'\\')   # escape \ first
        return "".join([nextStr for nextStr in escapedSeq(term)])



def returnOAISets(context):
        # returns list of tuples, in format (collection PID, OAI set name, OAI set ID)
        query_statement = "select $subject $setSpec $setName from <#ri> where { $subject <http://www.openarchives.org/OAI/2.0/setSpec> $setSpec . $subject <http://www.openarchives.org/OAI/2.0/setName> $setName . }"
        base_URL = "http://%s:%s@localhost/fedora/risearch" % (FEDORA_USER,FEDORA_PASSWORD)
        payload = {
                "lang" : "sparql",
                "query" : query_statement,
                "flush" : "false",
                "type" : "tuples",
                "format" : "JSON"
        }
        r = requests.post(base_URL, auth=HTTPBasicAuth(FEDORA_USER, FEDORA_PASSWORD), data=payload )
        risearch = json.loads(r.text)

        if context == "dropdown":
                shared_relationships = [ (each['subject'], each['setName']) for each in risearch['results'] ]   
        else:
                shared_relationships = [ (each['subject'], each['setName'], each['setSpec']) for each in risearch['results'] ]  

        return shared_relationships


def applicationError(error_msg):
        return render_template("applicationError.html",error_msg=error_msg)


# human readable file size
def sizeof_fmt(num, suffix='B'):
        for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
                if abs(num) < 1024.0:
                        return "%3.1f%s%s" % (num, unit, suffix)
                num /= 1024.0
        return "%.1f%s%s" % (num, 'Yi', suffix)


# remove duplicate elements from flat XML
def delDuplicateElements(XML):
    print "running XML element DUPE check"
    # Use a `set` to keep track of "visited" elements with good lookup time.
    seen = set()
    # The iter method does a recursive traversal
    for el in XML.iter('*'):        
        if (el.tag, el.text) in seen:
            print "removing duplicate XML tag: %s / %s" % (el.tag, el.text)
            el.getparent().remove(el)
        else:
            seen.add((el.tag,el.text))

    return XML


def imMode(im):
    # check for 16-bit tiffs
    print "Image mode:",im.mode
    if im.mode in ['I;16','I;16B']:
        print "I;16 tiff detected, converting..."
        im.mode = 'I'
        im = im.point(lambda i:i*(1./256)).convert('L')
    # else if not RGB, convert
    elif im.mode != "RGB" :
        print "Converting to RGB"
        im = im.convert("RGB")

    return im


# helper function for natural sorting
def natural_sort_key(s, _nsre=re.compile('([0-9]+)')):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(_nsre, s)]

# DECORATORS
#########################################################################################################
# decorated function will redirect if no objects currently selected 
def objects_needed(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):        
        try:
            username = session['username']
        except:
            return render_template("noObjs.html")
        userSelectedPIDs = models.user_pids.query.filter_by(username=username, status=True)
        if userSelectedPIDs.count() == 0:
            return render_template("noObjs.html")       
        return f(*args, **kwargs)       
    return decorated_function


# pass APP_PREFIX to all templates
@app.context_processor
def inject_prefix():
    return {
            'APP_PREFIX':APP_PREFIX,
            'APP_HOST':APP_HOST
    }


def sessionVarClean(session,var):
    try:
        del session[var]
        return True
    except:
        return False


# OPINIONATED MIMETYPES
#########################################################################################################
# WSUDOR opinionated mimes
opinionated_mimes = {
        # images
        "image/jp2":".jp2",
        "image/jpeg":".jpg",
        "audio/wav":".wav"
}   

# push to mimetypes.types_map
for k, v in opinionated_mimes.items():
        # reversed here
        mimetypes.types_map[v] = k


# def thumbForMime(mimetype):
    
#   # return thumbnail URL from WSUDOR_Thumbnails

#   if mimetype == 'application/pdf':
#       ds = 'PDF'

#   else:
#       ds = 'Unknown'

#   # return thumbnail URL
#   return 'http://%s/item/wayne:WSUDOR_Thumbnails/bitStream/%s?key=%s' % (localConfig.APP_HOST, ds, localConfig.BITSTREAM_KEY)


# OPINIONATED MIMETYPES for CONTENT TYPES
#########################################################################################################
mime_CM_hash = {

    # Document
    'application/pdf' : 'WSUDOR_Document',
    'application/vnd.oasis.opendocument.text' : 'WSUDOR_Document',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 'WSUDOR_Document',

    # Image
    'image/jpg' : 'WSUDOR_Image',
    'image/jpeg' : 'WSUDOR_Image',
    'image/tiff' : 'WSUDOR_Image',
    'image/tif' : 'WSUDOR_Image',
    'image/gif' : 'WSUDOR_Image',
    'image/png' : 'WSUDOR_Image',

    # Audio
    'audio/mpeg' : 'WSUDOR_Audio',
    'audio/wav' : 'WSUDOR_Audio',
    'audio/x-wav' : 'WSUDOR_Audio',

    # Video
    'video/mp4' : 'WSUDOR_Video',

}


# CUSTOM EXCEPTIONS
class IngestError(Exception):
    def __init__(self,*args,**kwargs):
        Exception.__init__(self,*args,**kwargs)


# Emailer
class Email():
    '''
    used to send email via an external smtp server
    '''

    def __init__(self):
        self.username = EMAIL_USERNAME
        self.password = EMAIL_PASSWORD
        self.server = EMAIL_SERVER
        self.port = EMAIL_SERVER_PORT

    def send(self, data):
        if data is None:
            return False
        else:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = data['subject']
            msg['From'] = data['from']
            msg['To'] = data['to']
            data['pid'] = data['pid'] if data['pid'] is None else "\n\nWSUDOR System Note: %s" % data['pid']
            data['msg'] = data['msg'] if data['pid'] is None else data['msg'] + data['pid']
            text = """%s""" % data['msg']
            msg.attach(MIMEText(text, 'plain'))

            try:
                s = smtplib.SMTP(EMAIL_SERVER, EMAIL_SERVER_PORT)
                s.sendmail(data['from'], data['to'], msg.as_string())
                s.ehlo()
                s.starttls()
                s.ehlo()
                s.login(EMAIL_USERNAME, EMAIL_PASSWORD)
                s.quit()
                return True
            except Exception, e:
                print e.__doc__
                print e.message
                return False
