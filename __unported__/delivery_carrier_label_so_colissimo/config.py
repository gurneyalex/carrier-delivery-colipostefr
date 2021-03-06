# -*- coding: utf-8 -*-
##############################################################################
#
#  licence AGPL version 3 or later
#  see licence in __openerp__.py or http://www.gnu.org/licenses/agpl-3.0.txt
#  Copyright (C) 2014 Akretion (http://www.akretion.com).
#  @author David BEAL <david.beal@akretion.com>
#
##############################################################################

from openerp.osv import orm
from . company import ResCompany


class ColiposteFrConfigSettings(orm.TransientModel):
    _inherit = 'colipostefr.config.settings'
    _companyObject = ResCompany
    _prefix = 'colipostefr_'
