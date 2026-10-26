"""Single source for the bot identity and combat rules version."""
BOT_NAME = 'dayuan'
RULES_VERSION = '0.1.198'
VERSION = RULES_VERSION + '-dev'
# Legacy 0.1.174 corresponds to the user-facing V1.74 release.
DISPLAY_NAME = f'{BOT_NAME} V{int(RULES_VERSION.rsplit(".",1)[1])/100:.2f}'
