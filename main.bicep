// main.bicep
// Deploy into the existing resource group with:
//   az deployment group create \
//     --resource-group rg-refinery-blastradius \
//     --template-file main.bicep
//
// Bicep deployments are idempotent -- re-running this against resources
// that already exist (with the same names) updates them in place rather
// than creating duplicates or erroring.
//
// Region is hardcoded to eastus, matching what this subscription actually
// allowed during manual setup (a tenant-level policy rejected several
// other regions for multiple resource types -- see SETUP_GUIDE.md).

param location string = 'eastus'
param adtName string = 'adt-refinery-blastradius'
param iotHubName string = 'iot-refinery-blastradius'
param storageAccountName string = 'strefinerybr'
param functionAppName string = 'func-refinery-cascade'
param acsName string = 'acs-refinery-dmz'
param emailServiceName string = 'email-refinery-dmz'
param alertEmailRecipient string = 'ryangoodwin0818@gmail.com'

// --- Storage account (required by the Function App for bookkeeping) ---
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
}

// --- Table Storage (alert history) ---
// Azure SQL Database is unavailable on this subscription (Azure for
// Students blocks new logical server creation subscription-wide, not
// just per-region -- confirmed across 5 tenant-policy-allowed regions
// via CLI and via the Portal free-offer flow). Table Storage reuses the
// storage account above, needs no new resource type, and is guaranteed
// to work here.
resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource alertsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-01-01' = {
  parent: tableService
  name: 'SwitchAlerts'
}

// --- Azure Digital Twins instance ---
resource adtInstance 'Microsoft.DigitalTwins/digitalTwinsInstances@2023-01-31' = {
  name: adtName
  location: location
  properties: {}
}

// --- IoT Hub (F1 free tier) ---
resource iotHub 'Microsoft.Devices/IotHubs@2023-06-30' = {
  name: iotHubName
  location: location
  sku: {
    name: 'F1'
    capacity: 1
  }
  properties: {
    eventHubEndpoints: {
      events: {
        partitionCount: 2
        retentionTimeInDays: 1
      }
    }
    // Without this, device messages ingress successfully but are dropped --
    // no custom routes are defined, and the fallback route (which sends
    // everything to the built-in "events" endpoint when nothing else
    // matches) is disabled by default.
    routing: {
      fallbackRoute: {
        source: 'DeviceMessages'
        condition: 'true'
        endpointNames: [
          'events'
        ]
        isEnabled: true
      }
    }
  }
}

// --- Application Insights (auto-created alongside the Function App originally;
//     defined explicitly here so it's reproducible rather than implicit) ---
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: functionAppName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

// --- Consumption plan (Dynamic SKU = pay-per-execution, matches the CLI's
//     --consumption-plan-location behavior) ---
resource hostingPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true // required for Linux
  }
}

// --- Function App ---
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned' // gives it the Managed Identity used for ADT auth
  }
  properties: {
    serverFarmId: hostingPlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'ADT_ENDPOINT'
          value: 'https://${adtInstance.properties.hostName}'
        }
        {
          name: 'EventHubConnectionString'
          value: 'Endpoint=${iotHub.properties.eventHubEndpoints.events.endpoint};SharedAccessKeyName=service;SharedAccessKey=${listKeys('${iotHub.id}/IotHubKeys/service', '2023-06-30').primaryKey};EntityPath=${iotHub.properties.eventHubEndpoints.events.path}'
        }
        {
          name: 'EVENT_HUB_NAME'
          value: iotHub.properties.eventHubEndpoints.events.path
        }
        {
          name: 'TABLES_CONNECTION_STRING'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'ACS_CONNECTION_STRING'
          value: acs.listKeys().primaryConnectionString
        }
        {
          name: 'ALERT_EMAIL_SENDER'
          value: 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}'
        }
        {
          name: 'ALERT_EMAIL_RECIPIENT'
          value: alertEmailRecipient
        }
      ]
    }
  }
}

// --- Azure Communication Services (email alerts) ---
resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: emailServiceName
  location: 'global'
  properties: {
    dataLocation: 'United States'
  }
}

// Azure Managed Domain: free donotreply@<guid>.azurecomm.net sender,
// no custom-domain DNS verification needed.
resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  properties: {
    domainManagement: 'AzureManaged'
  }
}

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: acsName
  location: 'global'
  properties: {
    dataLocation: 'United States'
    linkedDomains: [
      emailDomain.id
    ]
  }
}

// --- Grant the Function App's Managed Identity Data Owner on ADT ---
// Built-in role "Azure Digital Twins Data Owner":
var adtDataOwnerRoleId = 'bcd981a7-7f74-457b-83e1-cceb9e632ffe'

resource adtRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(adtInstance.id, functionApp.id, adtDataOwnerRoleId)
  scope: adtInstance
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', adtDataOwnerRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output adtHostName string = adtInstance.properties.hostName
output functionAppHostName string = functionApp.properties.defaultHostName
output alertEmailSender string = 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}'
