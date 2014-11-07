# -*- coding: utf-8 -*-
##############################################################################
#
#  licence AGPL version 3 or later
#  see licence in __openerp__.py or http://www.gnu.org/licenses/agpl-3.0.txt
#  Copyright (C) 2014 Akretion (http://www.akretion.com).
#  @author David BEAL <david.beal@akretion.com>
#          Sébastien BEAU
##############################################################################

from openerp.osv import orm, fields
from openerp.tools.config import config
from openerp.tools.translate import _
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from laposte_api.colissimo_and_so import (
    ColiPoste,
    InvalidDataForMako,
    InvalidWebServiceRequest)

from laposte_api.exception_helper import (
    InvalidWeight,
    InvalidSize,
    InvalidMissingField,
    InvalidCode,
    InvalidCountry,
    InvalidZipCode,
    InvalidSequence,
    InvalidKeyInTemplate,
    InvalidType)

from datetime import datetime

EXCEPT_TITLE = "'Colissimo and So' library Exception"
LABEL_TYPE = 'zpl2'
PACK_NUMBER = 0


def raise_exception(orm, message):
    raise orm.except_orm(EXCEPT_TITLE, map_except_message(message))


def map_except_message(message):
    """Allows to map vocabulary from external library
    to Odoo vocabulary in Exception message
    """
    webservice_mapping = {
        'line2': 'line2 (rue du partner du bon de livraison)',
        '\\xe8': 'e',
        '\\xe9': 'e',
        '\\xe0': 'a',
    }
    model_mapping = {
        'sender': 'company and \ncarrier configuration',
        'delivery': 'delivery order',
        'address': 'customer/partner'}
    for key, val in model_mapping.items():
        message = message.replace('(model: ' + key, '\n(check model: ' + val)
    for key, val in webservice_mapping.items():
        message = message.replace(key, val)
    if 'commercial afin de reinitialiser votre compte client' in message:
        message += ("\n\nEn gros à ce stade, "
                    "si vous avez saisi correctement votre identifiant"
                    "et mot de passe transmis par votre commercial"
                    "\nil est probable que ce dernier"
                    "n'a pas terminé le boulot jusqu'au bout"
                    "\nVraisemblablement, vous allez passez encore beaucoup"
                    "de temps à faire la balle de ping pong entre les"
                    "services: commercial, ADV et Support Intégration Clients."
                    "\nCe dernier est probablement votre meilleur chance."
                    "\nun homme averti en vaut deux"
                    "\nBougez avec la poste"
                    "\nBonne chance\n\n(the developer team)")
    return message


def move_label_content(content, tag, value, axis='y'):
    """ move label content
        :param content: unicode: whole text to parse
        :param tag: str: string to search in content for replacement purpose
        :param value: integer: define position x or y in the label
        :param axis: char: direction x or y
    """
    cpn = tag.split(',')
    if axis == 'y':
        position = str(int(cpn[1]) + value)
        new_tag = '%s,%s' % (cpn[0], position)
    else:
        extract_pos = int(cpn[0][3:])
        position = extract_pos + value
        new_tag = '%s%s,%s' % (cpn[0][:3], position, cpn[1])
    return content.replace(tag, new_tag)


def modify_label_content(content):
    """ International web service label is too long
        to be printed correctly
    """
    tags = ['^FO270,920', '^FO30,920', '^FO670,920', '^FO290,970',
            '^FO27,995', '^FO170,1194', '^FO27,988']
    for tag in tags:
        content = move_label_content(content, tag, -30)
    return content


class StockPicking(orm.Model):
    _inherit = 'stock.picking'

    def send_douane_doc(self, cr, uid, ids, field_n, arg, context=None):
        result = {}
        for elm in self.browse(cr, uid, ids):
            res = False
            if elm.state == 'done' and elm.carrier_type == 'colissimo':
                eu_country = False
                if elm.partner_id.country_id \
                        and elm.partner_id.country_id.intrastat:
                    # intrastat field identify european countries
                    eu_country = True
                if elm.carrier_code in ['8Q', '7Q']:
                    res = True
                if elm.carrier_code in ['EI', 'AI', 'SO'] and not eu_country:
                    res = True
                elif elm.carrier_code in ['9V', '9L'] \
                        and elm.partner_id.country_id \
                        and elm.partner_id.country_id.code == 'AD':
                    res = True
            result[elm.id] = res
        return result

    _columns = {
        'colipostefr_prise_en_charge': fields.char(
            '||| || |||| pch',
            size=64,
            help="""Code barre de prise en charge :
            cf documentation coliposte pour plus de détails
    - code étiquette sur 2 alfa.
    - coliss_order : valeur 1 ou 2 (selon la méthode de livraison)
    - code postal (5 alfa) ou   prefix pays (étranger)
      + 3 premiers caractères CP
    - N° du compte client fourni par le partner 'La Poste'
    - poids du colis sur 4 numeriques
    - 00 : assurance+recommandation (non implémenté à ce jour)
    - option 'non mécanisable' : valeur 1 ou 0
    - combinaison d'options : FTD+AR+CRBT (valeur de 0 à 7)
    - clé de liaison du code barre précédent sur 1 numérique
      (issu de l'avant dernier caractère)
    - clé de contrôle du code barre actuel sur 1 numérique
    """),
        'colipostefr_insur_recomm': fields.selection([
            ('01', '150 €'), ('02', '300 €'), ('03', '450 €'),
            ('04', '600 €'), ('05', '750 €'), ('06', '900 €'),
            ('07', '1050 €'), ('08', '1200 €'),
            ('09', '1350 €'), ('10', '1500 €'),
            # TODO Recommandation level
            #('21', 'R1'), ('22', 'R2'), ('23', 'R3'),
        ],
            'Insurance',
            help="Insurance amount in € (add valorem)"),
        'colipostefr_send_douane_doc': fields.function(
            send_douane_doc,
            string='Send douane document',
            type='boolean',
            store=False,
            help="Define if document CN23 et CN11 should be "
                 "printed/sent with the parcel"),
    }

    def _prepare_address_postefr(self, cr, uid, pick, context=None):
        address = {}
        for elm in ['name', 'city', 'zip', 'phone', 'mobile']:
            address[elm] = pick.partner_id[elm]
        # 3 is the number of fields street
        # 38 is the field street max length
        res = self.pool['res.partner']._get_split_address(
            cr, uid, pick.partner_id, 3, 38, context=context)
        address['street'], address['street2'], address['street3'] = res
        if pick.partner_id.country_id.code and pick.partner_id.country_id.code:
            address['countryCode'] = pick.partner_id.country_id.code
        return address

    def _prepare_option_postefr(self, cr, uid, pick, context=None):
        option = {}
        if pick.option_ids:
            for opt in pick.option_ids:
                opt_key = str(opt.tmpl_option_id['code'].lower())
                option[opt_key] = True
        if pick.colipostefr_insur_recomm:
            # TODO improve this mechanism option
            option['insurance'] = pick.colipostefr_insur_recomm
        return option

    def _prepare_sender_postefr(self, cr, uid, pick, context=None):
        partner = self.pool['stock.picking']._get_label_sender_address(
            cr, uid, pick, context=context)
        sender = {'support_city': pick.company_id.colipostefr_support_city,
                  'password': pick.company_id.colipostefr_password}
        if partner.country_id:
            sender['country'] = partner.country_id.name
        fields = ['name', 'street', 'zip', 'city',
                  'phone', 'mobile', 'email']
        for elm in fields:
            sender[elm] = partner[elm]
        if pick.carrier_code == '6J':
            sender['chargeur'] = pick.company_id.colipostefr_account_chargeur
        return sender

    def _get_packages_from_moves(self, cr, uid, picking, context=None):
        """ get all the packages of the picking
            no tracking_id will return a False (Browse Null), meaning that
            we want a label for the picking
        """
        move_ids = [move.id for move in picking.move_lines]
        moves = [move for move in picking.move_lines]
        packages = []
        moves_with_no_pack = []
        moves_with_pack = []
        move_ope_m = self.pool['stock.move.operation.link']
        move_ope_ids = move_ope_m.search(
            cr, uid, [('move_id', 'in', move_ids)], context=context)
        for move_ope in move_ope_m.browse(
                cr, uid, move_ope_ids, context=context):
            if move_ope.operation_id.result_package_id:
                packages.append(move_ope.operation_id.result_package_id)
                moves_with_pack.append(move_ope.move_id)
        moves_with_no_pack = set(moves) - set(moves_with_pack)
        if not packages:
            packages.append(False)
        return (packages, list(moves_with_no_pack))

    def _prepare_delivery_postefr(self, cr, uid, pick, number_of_packages,
                                  context=None):
        shipping_date = pick.min_date
        if pick.date_done:
            shipping_date = pick.date_done
        shipping_date = datetime.strptime(
            shipping_date, DEFAULT_SERVER_DATETIME_FORMAT)
        delivery = {
            'ref_client': '%s-pack_number/%s' % (pick.name, number_of_packages),
            'date': shipping_date.strftime('%d/%m/%Y'),
            'parcel_total_number': number_of_packages,
        }
        #if pick.carrier_code not in ['EI', 'AI', 'SO']:
        #    delivery.update({
        #        'cab_prise_en_charge': pick.colipostefr_prise_en_charge,
        #        'cab_suivi': pick.carrier_tracking_ref,
        #    })
        return delivery

    def _prepare_pack_postefr(
            self, cr, uid, packing, picking, option, service, france,
            weight=None, context=None):
        global PACK_NUMBER
        pack = {}
        PACK_NUMBER += 1
        if france:
            sequence = self._get_sequence(
                cr, uid, picking.carrier_code, context=context)
            #pack['carrier_tracking_ref'] = service.get_cab_suivi(
            pack['cab_suivi'] = service.get_cab_suivi(
                sequence)
            #pack['colipostefr_prise_en_charge'] = \
            pack['cab_prise_en_charge'] = \
                self._barcode_prise_en_charge_generate(
                    cr, uid, service, picking,
                    pack['cab_suivi'],
                    option, context=context)
        pack.update({
            'pack_number': PACK_NUMBER,
            'weight': 1,
            })
        #if weight:
        #    pack.update({
        #        'weight': "{0:05.2f}".format(weight),
        #        })
        #else:
        #    if tracking.move_ids:
        #        tracking_weight = [move.weight
        #                           for move in tracking.move_ids][0]
        #        pack.update({
        #            'weight': "{0:05.2f}".format(tracking_weight),
        #            })
        return pack

    def _generate_coliposte_label(
            self, cr, uid, picking, service, sender, address, france, option,
            package_ids=None, context=None):
        """ Generate labels and write package numbers received """
        global PACK_NUMBER
        PACK_NUMBER = 0
        carrier = {}
        deliv = {}
        label_info = {
             #'tracking_id': packing.id if packing else False,
             #'file': label['content'],
             'file_type': LABEL_TYPE,
        }
        pick2update = {}
        if package_ids is None:
            packages, moves_with_no_pack = self._get_packages_from_moves(
                cr, uid, picking, context=context)
        else:
            # restrict on the provided packages
            packages = self.pool['stock.quant.package'].browse(
                cr, uid, package_ids, context=context)
        labels = []
        without_pack = 0
        for pack in packages:
            if not pack:
                without_pack += 1
        pick2update['number_of_packages'] = len(packages) - without_pack + 1
        delivery = self._prepare_delivery_postefr(
            cr, uid, picking, pick2update['number_of_packages'],
            context=context)
        # Write packing_number on serial field
        # for move lines with package
        # and on picking for other moves
        for packing in packages:
            addr = address.copy()
            deliv.clear()
            deliv = delivery.copy()
            #import pdb;pdb.set_trace()
            if not packing:
                without_pack -= 1
                if without_pack > 0:
                    continue
                # only executed for the last move line with no package
                weight = sum([move.weight for move in moves_with_no_pack])
                #import pdb;pdb.set_trace()
                pack = self._prepare_pack_postefr(
                    cr, uid, packing, picking, option, service, france,
                    weight=weight, context=context)
                print '\n   pack from not packing', pack
                deliv.update(pack)
                ref_client = deliv['ref_client']
                deliv['ref_client'] = ref_client.replace(
                    'pack_number', str(pack['pack_number']))
                label = self.get_zpl(service, sender, deliv, addr, option)
                #pick2update['carrier_tracking_ref'] = label['tracking_number']
            else:
                pack = self._prepare_pack_postefr(
                    cr, uid, packing, picking, option, service, france,
                    context=context)
                pack['name'] = packing.name
                #pack['name'] = packing.get('nam
                print '       pack from REAL packing', pack
                deliv.update(pack)
                ref_client = deliv['ref_client']
                deliv['ref_client'] = ref_client.replace(
                    'pack_number', str(pack['pack_number']))
                label = self.get_zpl(service, sender, deliv, addr, option)
                #packing.write({'serial': label['tracking_number']})
            filename = deliv.get('ref_client', deliv['cab_suivi'].replace(' ', ''))
            print '    file', filename
            label_info.update({
                #'tracking_id': packing.id if packing else False,
                #'file': label['content'],
                'name': '%s.zpl' % filename.replace('/', '_'),
            })
                ## uncomment the line below to record a new test unit
                ## based on picking datas
                #if pick.company_id.colipostefr_unittest_helper and france:
                #    test_id = self._get_xmlid(cr, uid, pick.id) or 'tmp'
                #    service._set_unit_test_file_name(
                #        test_id, sequence, carrier['carrier_tracking_ref'],
                #        carrier['colipostefr_prise_en_charge'])

                #if label['tracking_number']:
                #    label_info['name'] = '%s%s.zpl' % (label['tracking_number'],
                #                                       label['filename'])
            if picking.carrier_code in ['EI', 'AI', 'SO']:
                label_info['file'] = modify_label_content(label[0])
                carrier['carrier_tracking_ref'] = label[2]
                carrier['colipostefr_prise_en_charge'] = label[3]
                self.write(cr, uid, [picking.id], carrier)
                picking = self.browse(cr, uid, picking.id, context=context)
                if label[1]:
                    self._create_comment(cr, uid, picking, label[1],
                                         context=None)
            else:
                label_info['file'] = label
                #if config.options.get('debug_mode', True):
                     ##get file datas in clipboard for paste in zebra viewer
                    #service._copy2clipboard(label['file'])
            print 'namef', label_info['name']
            labels.append(label_info)
            print [x['name'] for x in labels]
        print label_info.keys()
        print [x['name'] for x in labels]
        #self.write(cr, uid, picking.id, pick2update, context=context)
        #picking = self.browse(cr, uid, picking.id, context=context)
        self._customize_postefr_picking(cr, uid, picking, context=context)
        #import pdb;pdb.set_trace()
        return labels

    def get_zpl(self, service, sender, delivery, address, option):
        try:
            result = service.get_label(sender, delivery, address, option)
        except (InvalidMissingField,
                InvalidDataForMako,
                #InvalidValueNotInList,
                #InvalidAccountNumber,
                InvalidKeyInTemplate,
                InvalidWebServiceRequest,
                InvalidKeyInTemplate,
                InvalidCountry,
                InvalidZipCode,
                InvalidSequence,
                InvalidType) as e:
            raise_exception(orm, e.message)
        except Exception as e:
            if config.options.get('debug_mode', False):
                raise
            else:
                raise orm.except_orm(
                    "'Colissimo and So' Library Error", e.message)
        return result

    def _customize_postefr_picking(self, cr, uid, picking, context=None):
        "Use this method to override gls picking"
        return True

    def generate_shipping_labels(self, cr, uid, ids, package_ids=None,
                                 context=None):
        if isinstance(ids, (long, int)):
            ids = [ids]
        assert len(ids) == 1
        pick = self.browse(cr, uid, ids[0], context=context)
        if pick.carrier_type in ['colissimo', 'so_colissimo']:
            if not pick.carrier_code:
                raise orm.except_orm(
                    _("Carrier code missing"),
                    _("'Carrier code' is missing in '%s' delivery method"
                      % pick.carrier_type))
            try:
                account = pick.company_id.colipostefr_account
                service = ColiPoste(account).get_service(
                    pick.carrier_type, pick.carrier_code)
            except (InvalidSize, InvalidCode, InvalidType) as e:
                raise_exception(orm, e.message)
            except Exception as e:
                raise orm.except_orm(
                    "'Colissimo and So' Library Error",
                    map_except_message(e.message))
            france = True
            if pick.carrier_code in ['EI', 'AI', 'SO']:
                france = False
            option = self._prepare_option_postefr(
                cr, uid, pick, context=context)
            sender = self._prepare_sender_postefr(cr, uid, pick,
                                                  context=context)
            address = self._prepare_address_postefr(cr, uid, pick,
                                                    context=context)
            if not france:
                if not pick.partner_id.country_id \
                        and not pick.partner_id.country_id.code:
                    raise orm.except_orm(
                        "'Colissimo and So' Library Error",
                        "EI/AI/BE carrier code must have "
                        "a defined country code")
            return self._generate_coliposte_label(
                cr, uid, pick, service, sender, address, france, option,
                package_ids=package_ids, context=context)
        return super(StockPicking, self).generate_shipping_labels(
            cr, uid, ids, package_ids=package_ids, context=context)

    def _filter_message(self, cr, uid, mess_type, context=None):
        """ Allow to exclude returned message according their type.
            Only used by
        """
        if mess_type in ['INFOS']:
            return False
        return True

    def _create_comment(self, cr, uid, pick, messages, context=None):
        if pick.company_id.colipostefr_webservice_message:
            mess_title = "Web Service ColiPoste International<ul>%s</ul>"
            message = ''
            for mess in messages:
                if 'type' in mess:
                    if self._filter_message(cr, uid, mess['type'],
                                            context=context):
                        message += '<li>%s %s: %s</li>\n' \
                                   % (mess['type'],
                                      mess['id'],
                                      mess['libelle'])
                elif isinstance(mess, (str, unicode)):
                    message += unicode(mess)
            if len(message) > 0:
                vals = {
                    'res_id': pick.id,
                    'model': 'stock.picking',
                    'body': mess_title % message,
                    'type': 'comment',
                }
                self.pool['mail.message'].create(cr, uid, vals,
                                                 context=context)
        return True

    def _get_xmlid(self, cr, uid, id):
        "only used in development"
        xml_id_dict = self.get_xml_id(cr, uid, [id])
        xml_id = False
        if xml_id_dict:
            xml_id = xml_id_dict[id]
            xml_id = xml_id[xml_id.find('.')+1:]
        return xml_id.replace('stock_picking_', '')

    def _get_sequence(self, cr, uid, label, context=None):
        sequence = self.pool['ir.sequence'].next_by_code(
            cr, uid, 'stock.picking_' + label, context=context)
        if not sequence:
            raise orm.except_orm(
                _("Picking sequence"),
                _("There is no sequence defined for the label '%s'") % label)
        return sequence

    def _barcode_prise_en_charge_generate(
            self, cr, uid, service, picking, carrier_track, option,
            context=None):
        """
        :return: the second barcode
        """
        if picking.carrier_code:
            infos = {
                'zip': picking.partner_id.zip or '',
                'countryCode': picking.partner_id
                and picking.partner_id.country_id
                and picking.partner_id.country_id.code or '',
                'weight': picking.weight,
                'carrier_track': carrier_track,
            }
            infos.update(option)
            try:
                barcode = service.get_cab_prise_en_charge(infos)
            except (InvalidWeight, Exception) as e:
                raise_exception(orm, e.message)
        return barcode

    def copy(self, cr, uid, id, default=None, context=None):
        if default is None:
            default = {}
        default.update({
            'deposit_slip_id': None,
            'carrier_tracking_ref': None,
            'colipostefr_prise_en_charge': None,
        })
        return super(StockPicking, self).copy(
            cr, uid, id, default, context=context)

    def get_shipping_cost(self, cr, uid, ids, context=None):
        return 0

    def action_generate_carrier_label(self, cr, uid, ids, context=None):
        raise orm.except_orm(
            "Return label",
            "Return Label is not implemented for "
            "'Colissimo/So Colissimo' Coliposte \n"
            "Ask us for service proposal, http://www.akretion.com/contact")


class ShippingLabel(orm.Model):
    _inherit = 'shipping.label'

    def _get_file_type_selection(self, cr, uid, context=None):
        selection = super(ShippingLabel, self)._get_file_type_selection(
            cr, uid, context=None)
        selection.append(('zpl2', 'ZPL2'))
        selection = list(set(selection))
        return selection
