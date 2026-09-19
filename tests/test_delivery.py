import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.config import Config
from src.storage.history import History, write_text
from src.jobs.weekly_job import parser, run
from src.email.sender import send_report

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config(root=self.root, league_id=1, smtp_host='smtp.example.test',
            email_from='sender@example.test', report_email='reader@example.test')
        self.store = History(self.root, 1, 2026)
        self.store.save_state(4, {'league_id':1,'season':2026,'week':4,'report_generated':True,'report_preview':False})
        write_text(self.store.path('md',4), 'Report')
        write_text(self.store.path('html',4), '<p>Report</p>')

    def args(self, *flags):
        return parser().parse_args(['--week','4','--retry-email',*flags])

    def test_success_and_duplicate_prevention(self):
        sender = MagicMock()
        self.assertEqual(run(self.args(), self.config, sender=sender), 'email_sent')
        self.assertEqual(run(self.args(), self.config, sender=sender), 'already_delivered')
        self.assertEqual(sender.call_count, 1)

    def test_uncertain_send_not_retried_automatically(self):
        sender = MagicMock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            run(self.args(), self.config, sender=sender)
        self.assertFalse(self.store.state(4).get('email_sent',False))
        with self.assertRaises(RuntimeError):
            run(self.args(), self.config, sender=sender)
        self.assertEqual(sender.call_count,1)
        self.assertEqual(run(self.args('--resend-email'), self.config, sender=MagicMock()), 'email_sent')

    def test_preview_cannot_send(self):
        state = self.store.state(4)
        state['report_preview'] = True
        self.store.save_state(4,state)
        sender = MagicMock()
        with self.assertRaises(ValueError):
            run(self.args(), self.config, sender=sender)
        sender.assert_not_called()

    def test_dry_run_retry_does_not_send(self):
        sender = MagicMock()
        run(self.args('--dry-run'),self.config,sender=sender)
        sender.assert_not_called()
        self.assertFalse(self.store.state(4).get('email_sent',False))

    def test_lock_excludes_second_process(self):
        with self.store.lock():
            with self.assertRaises(RuntimeError):
                with self.store.lock():
                    pass

    def test_different_league_rejected(self):
        with self.store.lock():
            pass
        with self.assertRaises(ValueError):
            with History(self.root,2,2026).lock():
                pass

    @patch('src.email.sender.smtplib.SMTP')
    def test_multipart_and_tls(self, smtp):
        server = smtp.return_value.__enter__.return_value
        server.send_message.return_value = {}
        send_report(self.config,week=4,markdown='Plain report',html='<p>Report</p>',message_id='<test@example.test>')
        message = server.send_message.call_args.args[0]
        self.assertEqual(message.get_content_type(),'multipart/alternative')
        self.assertEqual(len(message.get_payload()),2)
        server.starttls.assert_called_once()

if __name__ == '__main__':
    unittest.main()
