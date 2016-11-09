# -*- coding: utf-8 -*-
# WSUDOR_API : views.py


# Ouroboros config
import localConfig

# WSUDOR_API_app
from WSUDOR_API import WSUDOR_API_app, api, models


#################################################################################
# TESTING
#################################################################################
api.add_resource(models.HelloWorld, '/%s/<string:name>' % (localConfig.WSUDOR_API_PREFIX), endpoint='helloworld')
api.add_resource(models.ArgParsing, '/%s/goober' % (localConfig.WSUDOR_API_PREFIX), endpoint='goober_integrity')


















