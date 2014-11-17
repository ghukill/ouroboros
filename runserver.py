# library
from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site
from twisted.internet import reactor, defer
from twisted.internet.task import deferLater
from twisted.web.server import NOT_DONE_YET
from twisted.web import server, resource
from twisted.python import log
from stompest.async import Stomp
from stompest.async.listener import SubscriptionListener
from stompest.config import StompConfig
from stompest.protocol import StompSpec
import json
import logging 

# for Ouroboros pid management
import os
import atexit
import lockfile

# local
from mainRouter import mainRouter
from localConfig import *

# import WSUDOR_Manager app
from WSUDOR_Manager import app

# import WSUDOR_API app
from WSUDOR_API import WSUDOR_API_app



# Ouroboros pidfile ##############################################################
# function to create/remove Ouroboros pidfile
def pidfileCreate():	
	print "Creating pidfile"
	fhand=open("/var/run/{APP_NAME}.pid".format(APP_NAME=APP_NAME),"w")
	fhand.write(str(os.getpid()))
	fhand.close()
	ouroboros_pidlock = lockfile.LockFile("/var/run/{APP_NAME}.pid".format(APP_NAME=APP_NAME))
	ouroboros_pidlock.acquire()			
	return ouroboros_pidlock
	
def pidfileRemove():
	print "Removing pidfile"
	ouroboros_pidlock.release()
	os.system("rm /var/run/{APP_NAME}.pid".format(APP_NAME=APP_NAME))


# WSU imageServer ##############################################################
'''
Prod: Listening on :61618, reverseproxy in Apache to :80/imageServer
Dev: Listening on :61620, reverseproxy in Apache to :80/imageServer-dev
'''
class imageServerListener(resource.Resource):
	isLeaf = True

	def _delayedImageServer(self,request):
		getParams = request.args

		# send to clearkRouter
		worker = mainRouter()
		# response = worker.imageServer(getParams=getParams)
		###################################
		image_dict = worker.imageServer(getParams=getParams)
		###################################

		# response 
		request.setHeader('Access-Control-Allow-Origin', '*')
		request.setHeader('Access-Control-Allow-Methods', 'GET, POST')
		request.setHeader('Access-Control-Allow-Headers','x-prototype-version,x-requested-with')
		request.setHeader('Access-Control-Max-Age', 2520)                
		request.setHeader('Content-Type', 'image/{mime}'.format(mime=image_dict['mime']))
		request.setHeader('Connection', 'Close')
		request.write(image_dict['img_binary'])
		request.finish()

	def render_GET(self, request):                
		d = deferLater(reactor, .01, lambda: request)
		d.addCallback(self._delayedImageServer)
		return NOT_DONE_YET


# Fedora Commons Messaging STOMP protocol consumer ##############################################################
'''
Prod: Connected to JSM Messaging service on :FEDCONSUMER_PORT (usually 61616), 
routes 'fedEvents' to mainRouter function from mainRouter.py
Dev: Disabled
'''
class fedoraConsumerWorker(object):
    QUEUE = "/topic/fedora.apim.update"
    def __init__(self, config=None):
        if config is None:
            config = StompConfig('tcp://localhost:{FEDCONSUMER_PORT}'.format(FEDCONSUMER_PORT=FEDCONSUMER_PORT))
        self.config = config

    @defer.inlineCallbacks
    def run(self):
        client = yield Stomp(self.config).connect()
        headers = {
            # client-individual mode is necessary for concurrent processing
            # (requires ActiveMQ >= 5.2)
            StompSpec.ACK_HEADER: StompSpec.ACK_CLIENT_INDIVIDUAL,
            # the maximal number of messages the broker will let you work on at the same time
            'activemq.prefetchSize': '100',
        }
        client.subscribe(self.QUEUE, headers, listener=SubscriptionListener(self.consume))

    def consume(self, client, frame):
        #send to clearkRouter           
        worker = mainRouter()        
        worker.fedoraConsumer(msg=frame.body)



# twisted liseners
logging.basicConfig(level=logging.DEBUG)

# WSUDOR_Manager
resource = WSGIResource(reactor, reactor.getThreadPool(), app)
site = Site(resource)

# WSUDOR_API_app
WSUDOR_API_resource = WSGIResource(reactor, reactor.getThreadPool(), WSUDOR_API_app)
WSUDOR_API_site = Site(WSUDOR_API_resource)

if __name__ == '__main__':

	# write PID to /var/run
	atexit.register(pidfileRemove)
	ouroboros_pidlock = pidfileCreate()

	# WSUDOR Manager
	if WSUDOR_MANAGER_FIRE == True:
		print "Starting WSUDOR_Manager..."
		reactor.listenTCP( WSUDOR_MANAGER_PORT, site)

	# WSUDOR_API
	if WSUDOR_API_FIRE == True:
		print "Starting WSUDOR_API_app..."
		reactor.listenTCP( WSUDOR_API_LISTENER_PORT, WSUDOR_API_site )	
	
	# imageServer
	if IMAGESERVER_FIRE == True:
		print "Starting imageServer..."
		reactor.listenTCP(IMAGESERVER_LISTENER_PORT, server.Site(imageServerListener()))	
	
	# fedConsumer
	if FEDCONSUMER_FIRE == True:
		print "Starting JSM listener..."
		fedoraConsumerWorker().run()


	print '''               
                ::+:/`              
         :----:+ssoo+:.`           
      `-:+sssossysoooooo+/-`       
    `:oysyo++ooooo+////+ooss+-`    
   :ssyy/-`   `..     ..:/+osso:   
 `/ssyo:                 `-+:oss+` 
 +sso+:                    `//sss+ 
.sssoo`                     `o+sss:
/syso+                    `-`+ooss+
ssyoo+                    ../oossss
osso+o.                  `+//ooysoo
:ysyo+o.                  `/++osos:
`+ssssoo:`   ``.-` .-    `-ooosss+`
 `ossso///-.--:.``::. `.:+ooossso` 
  `+sossyo++o++::///:/+ooossoss+`  
    -ossssss+oo+sossoosossssso-    
      ./osssssysyysssssssso/.      
         `-:++sosyssyyo+:.   
	'''
	print "<--Ouroboros says hissss-->"

	reactor.run()
