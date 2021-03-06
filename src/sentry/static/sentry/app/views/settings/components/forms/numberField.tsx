import React from 'react';

import InputField from './inputField';

type Props = InputField['props'];

export default function NumberField(props: Props) {
  return <InputField {...props} type="number" />;
}
