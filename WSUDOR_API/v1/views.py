# Ouroboros config
import localConfig

# python modules
import json

# flask proper
from flask import render_template, request, session, redirect, make_response, Response, Blueprint

# WSUDOR_API_app
from WSUDOR_API import WSUDOR_API_app
from WSUDOR_API_main import WSUDOR_API_main
from WSUDOR_Manager.helpers import gzipped

views_blueprint = Blueprint('views_v1', __name__)

# session data secret key
###############################################
WSUDOR_API_app.secret_key = 'WSUDOR-WSUDOR_API'
###############################################

# MAIN
#########################################################################################################
@views_blueprint.route("/", methods=['POST', 'GET'])
@gzipped
def index():		
	
	'''
	Twisted must have this parameter parsing built-in.
	For feeding WSUDOR_API_main in Flask app form, we perform here.
	'''	

	getParams = {each:request.values.getlist(each) for each in request.values}

	try:
		response = make_response(WSUDOR_API_main(getParams))
		response.headers['Access-Control-Allow-Origin'] = '*'
		response.headers['Access-Control-Allow-Methods'] = 'GET, POST'
		response.headers['Access-Control-Allow-Headers'] = 'x-prototype-version,x-requested-with'
		response.headers['Access-Control-Max-Age'] = 2520
		response.headers["Content-Type"] = "application/json"		
		response.headers['X-Powered-By'] = "['ShoppingHorse','DumpsterTurkey']"
		response.headers['Connection'] = 'Close'
		return response

	except Exception,e:
		print "WSUDOR_API call unsuccessful.  Error:",str(e)
		return '{"WSUDOR_API_status":"WSUDOR_API call unsuccessful.","WSUDOR_API_message":%s}' % (json.dumps(str(e)))
	


