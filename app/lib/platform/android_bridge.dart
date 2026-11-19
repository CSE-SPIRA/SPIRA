import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

import '../api/app_api.dart';

class ShareInbox {
  const ShareInbox(this.orders, this.issue);
  final List<SharedOrder> orders;
  final String? issue;
}

abstract interface class AppPlatform {
  Stream<void> get sharesChanged;
  Future<ShareInbox> inbox(String scope);
  Future<void> acknowledge(String scope, String sourceId, String episodeId);
  Future<void> discardInvalid(String scope, String sourceId);
  Future<bool> notify(String scope, String key, String title, String text);
  Future<void> requestNotificationPermission();
}

class AndroidBridge implements AppPlatform {
  AndroidBridge() {
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'sharesChanged') _shareEvents.add(null);
    });
  }

  static const _channel = MethodChannel('spira/app');
  final _shareEvents = StreamController<void>.broadcast();

  @override
  Stream<void> get sharesChanged => _shareEvents.stream;

  @override
  Future<ShareInbox> inbox(String scope) async {
    final result = (await _channel.invokeMapMethod<String, Object?>(
      'inbox',
      scope,
    ))!;
    final records = result['orders']! as List<Object?>;
    return ShareInbox([
      for (final record in records.cast<Map<Object?, Object?>>())
        SharedOrder(
          record['sourceId']! as String,
          record['sharedAt']! as String,
          (record['images']! as List<Object?>)
              .cast<String>()
              .map(File.new)
              .toList(),
        ),
    ], result['issue'] as String?);
  }

  @override
  Future<void> acknowledge(String scope, String sourceId, String episodeId) =>
      _channel.invokeMethod<void>('acknowledge', {
        'scope': scope,
        'sourceId': sourceId,
        'episodeId': episodeId,
      });

  @override
  Future<void> discardInvalid(String scope, String sourceId) =>
      _channel.invokeMethod<void>('discardInvalid', {
        'scope': scope,
        'sourceId': sourceId,
      });

  @override
  Future<bool> notify(
    String scope,
    String key,
    String title,
    String text,
  ) async => (await _channel.invokeMethod<bool>('notify', {
    'scope': scope,
    'key': key,
    'title': title,
    'text': text,
  }))!;

  @override
  Future<void> requestNotificationPermission() =>
      _channel.invokeMethod<void>('requestNotificationPermission');
}
