from __future__ import absolute_import

import six
import logging

from django.utils.translation import ugettext_lazy as _


from sentry.integrations import (
    IntegrationInstallation,
    IntegrationFeatures,
    IntegrationProvider,
    IntegrationMetadata,
    FeatureDescription,
)
from sentry import options
from sentry.pipeline import NestedPipelineView
from sentry.identity.pipeline import IdentityProviderPipeline
from sentry.utils.http import absolute_uri
from sentry.models import (
    Project,
    ProjectKey,
    User,
    SentryAppInstallation,
    SentryAppInstallationForProvider,
)
from sentry.utils.compat import map
from sentry.shared_integrations.exceptions import IntegrationError, ApiError
from sentry.mediators.sentry_apps import InternalCreator

from .client import VercelClient

logger = logging.getLogger("sentry.integrations.vercel")

DESCRIPTION = """
VERCEL DESC
"""

FEATURES = [
    FeatureDescription(
        """
        DEPLOYMENT DESCRIPTION
        """,
        IntegrationFeatures.DEPLOYMENT,
    ),
]

INSTALL_NOTICE_TEXT = (
    "Visit the Vercel Marketplace to install this integration. After installing the"
    " Sentry integration, you'll be redirected back to Sentry to finish syncing Vercel and Sentry projects."
)


external_install = {
    "url": u"https://vercel.com/integrations/%s/add" % options.get("vercel.integration-slug"),
    "buttonText": _("Vercel Marketplace"),
    "noticeText": _(INSTALL_NOTICE_TEXT),
}


metadata = IntegrationMetadata(
    description=DESCRIPTION.strip(),
    features=FEATURES,
    author="The Sentry Team",
    noun=_("Installation"),
    issue_url="https://github.com/getsentry/sentry/issues/new?title=Vercel%20Integration:%20&labels=Component%3A%20Integrations",
    source_url="https://github.com/getsentry/sentry/tree/master/src/sentry/integrations/vercel",
    aspects={"externalInstall": external_install},
)

internal_integration_overview = (
    "This internal integration was auto-generated during the installation process of your Vercel"
    " integration. It is needed to provide the token used to create a release. If this integration is "
    "deleted, your Vercel integration will stop working!"
)


class VercelIntegration(IntegrationInstallation):
    def get_client(self):
        access_token = self.model.metadata["access_token"]
        if self.model.metadata["installation_type"] == "team":
            return VercelClient(access_token, self.model.external_id)

        return VercelClient(access_token)

    def get_organization_config(self):
        vercel_client = self.get_client()
        # TODO: add try/catch if we get API failure
        vercel_projects = [
            {"value": p["id"], "label": p["name"]} for p in vercel_client.get_projects()
        ]

        proj_fields = ["id", "platform", "name", "slug"]
        sentry_projects = map(
            lambda proj: {key: proj[key] for key in proj_fields},
            (
                Project.objects.filter(organization_id=self.organization_id)
                .order_by("slug")
                .values(*proj_fields)
            ),
        )

        fields = [
            {
                "name": "project_mappings",
                "type": "project_mapper",
                "mappedDropdown": {
                    "items": vercel_projects,
                    "placeholder": "Select a Vercel Project",  # TOOD: add translation
                },
                "sentryProjects": sentry_projects,
            }
        ]

        return fields

    def update_organization_config(self, data):
        # data = {"project_mappings": [[sentry_project_id, vercel_project_id]]}

        metadata = self.model.metadata
        vercel_client = VercelClient(metadata["access_token"], metadata.get("team_id"))
        config = self.org_integration.config
        [sentry_project_id, vercel_project_id] = data["project_mappings"][
            -1
        ]  # TODO: update this to work in the case where a project is removed
        sentry_project = Project.objects.get(id=sentry_project_id)
        enabled_dsn = ProjectKey.get_default(project=sentry_project)
        if not enabled_dsn:
            raise IntegrationError("You must have an enabled DSN to continue!")
        sentry_project_dsn = enabled_dsn.get_dsn(public=True)

        org_secret = self.create_secret(
            vercel_client, vercel_project_id, "SENTRY_ORG", sentry_project.organization.slug
        )
        project_secret = self.create_secret(
            vercel_client,
            vercel_project_id,
            "SENTRY_PROJECT_%s" % sentry_project_id,
            sentry_project.slug,
        )
        dsn_secret = self.create_secret(
            vercel_client,
            vercel_project_id,
            "NEXT_PUBLIC_SENTRY_DSN_%s" % sentry_project_id,
            sentry_project_dsn,
        )

        self.create_env_var(vercel_client, vercel_project_id, "SENTRY_ORG", org_secret)
        self.create_env_var(vercel_client, vercel_project_id, "SENTRY_PROJECT", project_secret)
        self.create_env_var(vercel_client, vercel_project_id, "NEXT_PUBLIC_SENTRY_DSN", dsn_secret)

        config.update(data)
        self.org_integration.update(config=config)

    def get_env_vars(self, client, vercel_project_id):
        return client.get_env_vars(vercel_project_id)

    def get_secret(self, client, name):
        try:
            return client.get_secret(name)
        except ApiError as e:
            if e.code == 404:
                return None
            raise

    def env_var_already_exists(self, client, vercel_project_id, name):
        return any(
            [
                env_var
                for env_var in self.get_env_vars(client, vercel_project_id)["envs"]
                if env_var["key"] == name
            ]
        )

    def create_secret(self, client, vercel_project_id, name, value):
        secret = self.get_secret(client, name)
        if secret:
            return secret
        else:
            return client.create_secret(vercel_project_id, name, value)

    def create_env_var(self, client, vercel_project_id, key, value):
        if not self.env_var_already_exists(client, vercel_project_id, key):
            client.create_env_variable(vercel_project_id, key, value)


class VercelIntegrationProvider(IntegrationProvider):
    key = "vercel"
    name = "Vercel"
    requires_feature_flag = True
    can_add = False
    metadata = metadata
    integration_cls = VercelIntegration
    features = frozenset([IntegrationFeatures.DEPLOYMENT])
    oauth_redirect_url = "/extensions/vercel/configure/"

    def get_pipeline_views(self):
        identity_pipeline_config = {"redirect_url": absolute_uri(self.oauth_redirect_url)}

        identity_pipeline_view = NestedPipelineView(
            bind_key="identity",
            provider_key=self.key,
            pipeline_cls=IdentityProviderPipeline,
            config=identity_pipeline_config,
        )

        return [identity_pipeline_view]

    def build_integration(self, state):
        data = state["identity"]["data"]
        access_token = data["access_token"]
        team_id = data.get("team_id")
        client = VercelClient(access_token, team_id)

        if team_id:
            external_id = team_id
            installation_type = "team"
            team = client.get_team()
            name = team["name"]
        else:
            external_id = data["user_id"]
            installation_type = "user"
            user = client.get_user()
            name = user["name"]

        try:
            webhook = client.create_deploy_webhook()
        except ApiError as err:
            logger.info(
                "vercel.create_webhook.failed",
                extra={"error": six.text_type(err), "external_id": external_id},
            )
            try:
                details = err.json["messages"][0].values().pop()
            except Exception:
                details = "Unknown Error"
            message = u"Could not create deployment webhook in Vercel: {}".format(details)
            raise IntegrationError(message)

        integration = {
            "name": name,
            "external_id": external_id,
            "metadata": {
                "access_token": access_token,
                "installation_id": data["installation_id"],
                "installation_type": installation_type,
                "webhook_id": webhook["id"],
            },
            "post_install_data": {"user_id": state["user_id"]},
        }

        return integration

    def post_install(self, integration, organization, extra=None):
        # check if we have an installation already
        if SentryAppInstallationForProvider.objects.filter(
            organization=organization, provider="vercel"
        ).exists():
            logger.info(
                "vercel.post_install.installation_exists",
                extra={"organization_id": organization.id},
            )
            return

        user = User.objects.get(id=extra.get("user_id"))
        data = {
            "name": "Vercel Internal Integration",
            "author": "Auto-generated by Sentry",
            "organization": organization,
            "overview": internal_integration_overview.strip(),
            "user": user,
            "scopes": ["project:releases"],
        }
        # create the internal integration and link it to the join table
        sentry_app = InternalCreator.run(**data)
        sentry_app_installation = SentryAppInstallation.objects.get(sentry_app=sentry_app)
        SentryAppInstallationForProvider.objects.create(
            sentry_app_installation=sentry_app_installation,
            organization=organization,
            provider="vercel",
        )
